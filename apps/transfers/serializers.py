from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import ProductStock

from .models import StockTransfer, StockTransferItem


def is_admin_user(user):
    """Return True for Django superusers and users assigned the ADMIN role."""
    if not user or not user.is_authenticated:
        return False

    role_code = getattr(getattr(user, "role", None), "code", "")
    return bool(user.is_superuser or str(role_code).upper() == "ADMIN")


class ItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    variant_label = serializers.CharField(
        source="variant.__str__", read_only=True, default=""
    )

    class Meta:
        model = StockTransferItem
        exclude = ["transfer"]


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

    def validate(self, attrs):
        from_branch = attrs.get("from_branch") or getattr(
            self.instance, "from_branch", None
        )
        to_branch = attrs.get("to_branch") or getattr(self.instance, "to_branch", None)

        if from_branch == to_branch:
            raise serializers.ValidationError(
                {
                    "to_branch": "Destination branch must be different from source branch."
                }
            )

        items = attrs.get("items", [])
        item_errors = []
        seen_products = set()
        for item in items:
            product = item.get("product")
            quantity = int(item.get("requested_quantity") or 0)
            if not product or not from_branch:
                continue

            if product.id in seen_products:
                item_errors.append(
                    f"{product.sku}: the same product cannot be added more than once."
                )
                continue
            seen_products.add(product.id)

            variant = item.get("variant")
            if variant and variant.product_id != product.id:
                item_errors.append(
                    f"{product.sku}: selected variant does not belong to this product."
                )
                continue

            stock = ProductStock.objects.filter(
                product=product,
                branch=from_branch,
                variant=variant,
            ).first()
            available = stock.available_stock if stock else 0
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

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        request = self.context["request"]
        admin_created = is_admin_user(request.user)

        # Respect a date submitted by the form, while keeping today as a safe default.
        transfer_date = validated_data.pop("transfer_date", timezone.localdate())

        transfer = StockTransfer.objects.create(
            **validated_data,
            transfer_number=f"TR-{timezone.now():%Y%m%d%H%M%S%f}",
            requested_by=request.user,
            approved_by=request.user if admin_created else None,
            transfer_date=transfer_date,
            status="APPROVED" if admin_created else "REQUESTED",
        )
        StockTransferItem.objects.bulk_create(
            [StockTransferItem(transfer=transfer, **item) for item in items]
        )
        return transfer
