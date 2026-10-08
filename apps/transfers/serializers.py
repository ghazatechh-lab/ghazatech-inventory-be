from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import ProductStock
from apps.inventory.services import resolve_unit_cost_excluding_vat
from apps.branch_data.services import database_alias_for_branch
from apps.branch_data.physical import request_active_branch, require_physical_branch, is_physical_branch
from apps.common.tax import calculate_inventory_tax, quantize_money, quantize_unit

from .models import StockTransfer, StockTransferItem


def is_admin_user(user):
    """Return True for Django superusers and users assigned the ADMIN role."""
    if not user or not user.is_authenticated:
        return False

    role_code = getattr(getattr(user, "role", None), "code", "")
    return bool(user.is_superuser or str(role_code).upper() == "ADMIN")


class ItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )
    variant_label = serializers.SerializerMethodField()

    class Meta:
        model = StockTransferItem
        fields = [
            "id",
            "product",
            "product_name",
            "sku",
            "variant",
            "variant_label",
            "requested_quantity",
            "dispatched_quantity",
            "received_quantity",
            "damaged_quantity",
            "remarks",
            "transfer_unit_cost",
            "line_transfer_value",
            "source_value",
            "destination_value",
            "value_difference",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "sku",
            "variant_label",
            "dispatched_quantity",
            "received_quantity",
            "damaged_quantity",
            "transfer_unit_cost",
            "line_transfer_value",
            "source_value",
            "destination_value",
            "value_difference",
        ]

    def get_variant_label(self, obj):
        if not obj.variant_id:
            return ""

        return str(obj.variant)


class TransferSerializer(serializers.ModelSerializer):
    items = ItemSerializer(many=True)
    from_branch_name = serializers.CharField(
        source="from_branch.branch_name", read_only=True
    )
    from_branch_code = serializers.CharField(
        source="from_branch.branch_code", read_only=True
    )
    to_branch_name = serializers.CharField(
        source="to_branch.branch_name", read_only=True
    )
    to_branch_code = serializers.CharField(
        source="to_branch.branch_code", read_only=True
    )
    requested_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = StockTransfer
        fields = "__all__"
        read_only_fields = [
            "transfer_number",
            "requested_by",
            "approved_by",
            "dispatched_by",
            "received_by",
            "dispatch_date",
            "received_date",
            "status",
            "created_at",
            "updated_at",
            "tax_scope",
            "transfer_value",
            "capitalized_vat_value",
            "courier_cost_excluding_vat",
            "courier_vat_treatment",
            "courier_vat_percentage",
            "courier_vat_amount",
            "courier_total",
            "total_transfer_cost",
            "source_stock_value",
            "destination_stock_value",
            "reconciliation_status",
            "value_difference",
        ]

    @staticmethod
    def _user_display_name(user):
        if not user:
            return ""
        return user.full_name or user.get_full_name() or user.email or user.username

    def get_requested_by_name(self, obj):
        return self._user_display_name(obj.requested_by)

    def get_approved_by_name(self, obj):
        return self._user_display_name(obj.approved_by)

    def get_item_count(self, obj):
        prefetched = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("items")

        if prefetched is not None:
            return len(prefetched)

        return obj.items.count()

    def get_total_quantity(self, obj):
        prefetched = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("items")

        if prefetched is not None:
            return sum(int(item.requested_quantity or 0) for item in prefetched)

        return sum(
            int(quantity or 0)
            for quantity in obj.items.values_list(
                "requested_quantity",
                flat=True,
            )
        )

    def validate(self, attrs):
        from_branch = attrs.get("from_branch") or getattr(
            self.instance, "from_branch", None
        )
        to_branch = attrs.get("to_branch") or getattr(self.instance, "to_branch", None)

        request = self.context.get("request")
        active_branch = request_active_branch(request)

        # In a physical branch UI the source is always the active branch and
        # cannot be overridden by a crafted payload. In BR03 the source must be
        # selected explicitly, but it still has to be BR01 or BR02.
        if active_branch and is_physical_branch(active_branch):
            from_branch = active_branch
            attrs["from_branch"] = active_branch

        require_physical_branch(from_branch, field="from_branch")
        require_physical_branch(to_branch, field="to_branch")

        if self.instance and from_branch.pk != self.instance.from_branch_id:
            raise serializers.ValidationError({"from_branch": "The source branch cannot be changed after the transfer is created."})

        if from_branch.pk == to_branch.pk:
            raise serializers.ValidationError(
                {
                    "to_branch": "Destination branch must be different from source branch."
                }
            )

        items = attrs.get("items", [])

        if not items:
            raise serializers.ValidationError(
                {"items": ["Add at least one transfer item."]}
            )

        item_errors = []
        seen_products = set()
        for item in items:
            product = item.get("product")
            quantity = int(item.get("requested_quantity") or 0)
            if not product or not from_branch:
                continue

            if quantity <= 0:
                item_errors.append(
                    f"{product.sku}: quantity must be greater than zero."
                )
                continue

            variant = item.get("variant")
            duplicate_key = (
                product.id,
                variant.id if variant else None,
            )

            if duplicate_key in seen_products:
                item_errors.append(
                    (
                        f"{product.sku}: this product and "
                        "attribute combination was added more than once."
                    )
                )
                continue

            seen_products.add(duplicate_key)

            if variant and variant.product_id != product.id:
                item_errors.append(
                    f"{product.sku}: selected variant does not belong to this product."
                )
                continue

            stock_db = database_alias_for_branch(from_branch)
            stock_rows = list(
                ProductStock.objects.using(stock_db).filter(
                    product_id=product.id,
                    branch_id=from_branch.id,
                    variant_id=(variant.id if variant else None),
                )
            )
            available = sum(int(row.available_stock or 0) for row in stock_rows)
            if available <= 0:
                item_errors.append(
                    f"{product.sku}: no available stock in {from_branch.branch_code}."
                )
            elif quantity > available:
                item_errors.append(
                    f"{product.sku}: requested {quantity}, available {available}."
                )

        if item_errors:
            raise serializers.ValidationError({"items": item_errors})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not items:
            raise serializers.ValidationError(
                {"items": ["Add at least one transfer item."]}
            )

        request = self.context["request"]
        admin_created = is_admin_user(request.user)

        transfer_date = validated_data.pop(
            "transfer_date",
            timezone.localdate(),
        )

        validated_data["tax_scope"] = "OUT_OF_SCOPE"
        validated_data["courier_cost_excluding_vat"] = Decimal("0.00")
        validated_data["courier_vat_treatment"] = "OUT_OF_SCOPE"
        validated_data["courier_vat_percentage"] = Decimal("0.00")
        validated_data["courier_vat_amount"] = Decimal("0.00")
        validated_data["courier_total"] = Decimal("0.00")

        transfer = StockTransfer.objects.create(
            **validated_data,
            transfer_number=(f"TR-{timezone.now():%Y%m%d%H%M%S%f}"),
            requested_by=request.user,
            approved_by=(request.user if admin_created else None),
            approved_at=(timezone.now() if admin_created else None),
            transfer_date=transfer_date,
            status=("APPROVED" if admin_created else "REQUESTED"),
        )

        transfer_value = Decimal("0.00")

        for item_data in items:
            product = item_data["product"]
            variant = item_data.get("variant")
            classification = (
                str(
                    item_data.get(
                        "REGULAR",
                    )
                )
                .strip()
                .upper()
            )
            quantity = int(item_data["requested_quantity"])

            stock_db = database_alias_for_branch(transfer.from_branch)
            stock_rows = list(
                ProductStock.objects.using(stock_db).filter(
                    product_id=product.id,
                    branch_id=transfer.from_branch_id,
                    variant_id=(variant.id if variant else None),
                )
            )

            if not stock_rows:
                raise serializers.ValidationError(
                    {"items": [f"{product.sku}: stock record was not found in the source branch."]}
                )

            available_quantity = sum(
                int(row.available_stock or 0) for row in stock_rows
            )
            if quantity > available_quantity:
                raise serializers.ValidationError(
                    {"items": [f"{product.sku}: requested {quantity}, available {available_quantity}."]}
                )

            weighted_value = Decimal("0")
            weighted_qty = 0
            for row in stock_rows:
                row_qty = max(0, int(row.available_stock or 0))
                if row_qty <= 0:
                    continue
                row_cost = resolve_unit_cost_excluding_vat(
                    row, product=product, variant=variant
                )
                weighted_value += Decimal(row_qty) * row_cost
                weighted_qty += row_qty
            unit_cost = quantize_unit(
                weighted_value / Decimal(weighted_qty)
                if weighted_qty
                else resolve_unit_cost_excluding_vat(
                    stock_rows[0], product=product, variant=variant
                )
            )

            line_value = quantize_money(unit_cost * Decimal(quantity))

            StockTransferItem.objects.create(
                transfer=transfer,
                product=product,
                variant=variant,
                requested_quantity=quantity,
                remarks=str(item_data.get("remarks", "") or "").strip(),
                transfer_unit_cost=unit_cost,
                line_transfer_value=line_value,
                source_value=line_value,
            )

            transfer_value += line_value

        saved_item_count = StockTransferItem.objects.filter(transfer=transfer).count()

        if saved_item_count != len(items):
            raise serializers.ValidationError(
                {
                    "items": [
                        (
                            "The transfer was not saved because "
                            "one or more item rows were missing."
                        )
                    ]
                }
            )

        transfer.transfer_value = quantize_money(transfer_value)
        transfer.source_stock_value = transfer.transfer_value
        transfer.total_transfer_cost = transfer.transfer_value
        transfer.save(
            update_fields=[
                "transfer_value",
                "source_stock_value",
                "total_transfer_cost",
                "updated_at",
            ]
        )

        return (
            StockTransfer.objects.select_related(
                "from_branch",
                "to_branch",
                "requested_by",
                "approved_by",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
            )
            .get(pk=transfer.pk)
        )
