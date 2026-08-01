import json

from django.db import transaction
from rest_framework import serializers

from .services import adjust_stock

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    ProductVariant,
    Rack,
    StockAdjustment,
    StockMovement,
)


def get_requested_branch_id(serializer):
    request = (
        serializer.context.get("request") if hasattr(serializer, "context") else None
    )
    if not request:
        return None
    value = request.query_params.get("branch")
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def variant_label(variant):
    if not variant:
        return "Base product"

    if variant.is_base or not variant.attributes:
        return "Base product"

    return (
        " / ".join(
            str(value)
            for value in variant.attributes.values()
            if value not in (None, "")
        )
        or "Variant"
    )


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class RackSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )

    class Meta:
        model = Rack
        fields = [
            "id",
            "branch",
            "branch_name",
            "branch_code",
            "rack_code",
            "rack_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "branch_name",
            "branch_code",
            "created_at",
            "updated_at",
        ]


class ProductVariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    # These values are accepted only while creating/editing a product. They
    # initialize the branch ProductStock row; they are not duplicate balances
    # stored on ProductVariant.
    initial_regular_stock = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=0,
    )
    initial_restricted_stock = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=0,
    )

    # Backward-compatible field used by older screens. It represents total
    # available stock for the requested branch.
    available_qty = serializers.IntegerField(read_only=True)
    regular_quantity = serializers.SerializerMethodField()
    restricted_quantity = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()

    purchase_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "attributes",
            "display_name",
            "initial_regular_stock",
            "initial_restricted_stock",
            "available_qty",
            "regular_quantity",
            "restricted_quantity",
            "total_quantity",
            "purchase_price",
            "retail_price",
            "wholesale_price",
            "minimum_selling_price",
            "is_base",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "display_name",
            "available_qty",
            "regular_quantity",
            "restricted_quantity",
            "total_quantity",
            "is_base",
            "created_at",
            "updated_at",
        ]

    def get_display_name(self, obj):
        return variant_label(obj)

    def _stock(self, obj):
        product = obj.product
        branch_id = get_requested_branch_id(self) or product.branch_id
        if not branch_id:
            return None
        stock_variant = obj if product.has_variants else None
        return ProductStock.objects.filter(
            product=product,
            variant=stock_variant,
            branch_id=branch_id,
        ).first()

    def _can_view_restricted(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or getattr(getattr(user, "role", None), "code", "") == "ADMIN"
                or user.has_perm("inventory.view_restricted_stock")
            )
        )

    def get_regular_quantity(self, obj):
        stock = self._stock(obj)
        return int(stock.regular_quantity or 0) if stock else 0

    def get_restricted_quantity(self, obj):
        if not self._can_view_restricted():
            return None
        stock = self._stock(obj)
        return int(stock.restricted_quantity or 0) if stock else 0

    def get_total_quantity(self, obj):
        stock = self._stock(obj)
        if not stock:
            return 0
        if self._can_view_restricted():
            return int(stock.total_quantity)
        return int(stock.regular_quantity or 0)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        stock = self._stock(instance)
        data["available_qty"] = (
            int(stock.total_quantity)
            if stock and self._can_view_restricted()
            else int(stock.regular_quantity or 0) if stock else 0
        )
        if not self._can_view_restricted():
            data.pop("restricted_quantity", None)
        return data

    def validate_attributes(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Attributes must be key-value pairs.")
        return {
            str(key).strip(): str(item_value).strip()
            for key, item_value in value.items()
            if str(key).strip() and str(item_value).strip()
        }


class ProductSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(
        source="brand.name",
        read_only=True,
    )
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    branch_name = serializers.SerializerMethodField()
    branch_code = serializers.SerializerMethodField()
    rack_code = serializers.SerializerMethodField()
    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
        allow_null=True,
    )

    product_image_url = serializers.SerializerMethodField()

    variants = ProductVariantSerializer(
        many=True,
        required=False,
    )

    total_available_qty = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"

        read_only_fields = [
            "created_at",
            "updated_at",
            "is_deleted",
        ]

        extra_kwargs = {
            "barcode": {
                "required": False,
                "allow_blank": True,
                "allow_null": True,
            },
        }

    def _selected_branch(self, obj):
        branch_id = get_requested_branch_id(self)
        if not branch_id:
            return obj.branch

        stock = obj.stocks.filter(branch_id=branch_id).select_related("branch").first()
        return stock.branch if stock else obj.branch

    def get_branch_name(self, obj):
        branch = self._selected_branch(obj)
        return branch.branch_name if branch else None

    def get_branch_code(self, obj):
        branch = self._selected_branch(obj)
        return branch.branch_code if branch else None

    def get_rack_code(self, obj):
        branch_id = get_requested_branch_id(self)
        if branch_id and obj.rack_id and obj.rack.branch_id != branch_id:
            return None
        return obj.rack.rack_code if obj.rack_id else None

    def get_product_image_url(self, obj):
        if not obj.product_image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.product_image.url)

        return obj.product_image.url

    def get_total_available_qty(self, obj):
        stocks = obj.stocks.all()
        branch_id = get_requested_branch_id(self)
        if branch_id:
            stocks = stocks.filter(branch_id=branch_id)

        return sum(max(0, stock.available_stock) for stock in stocks)

    def to_internal_value(self, data):
        """
        Convert QueryDict or normal dictionary into mutable data.

        Also converts empty barcode values into None so PostgreSQL
        does not receive duplicate empty strings for a unique field.
        """
        mutable = (
            {key: data.get(key) for key in data.keys()}
            if hasattr(data, "getlist")
            else dict(data)
        )

        barcode = mutable.get(
            "barcode",
            serializers.empty,
        )

        if barcode is not serializers.empty:
            if barcode is None:
                mutable["barcode"] = None
            else:
                normalized_barcode = str(barcode).strip()

                mutable["barcode"] = normalized_barcode if normalized_barcode else None

        variants = mutable.get(
            "variants",
            serializers.empty,
        )

        if variants is not serializers.empty:
            if variants in (
                None,
                "",
            ):
                mutable["variants"] = []

            elif isinstance(
                variants,
                str,
            ):
                try:
                    mutable["variants"] = json.loads(variants)

                except json.JSONDecodeError as exc:
                    raise serializers.ValidationError(
                        {"variants": ("Invalid variant data.")}
                    ) from exc

        return super().to_internal_value(mutable)

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        rack = attrs.get(
            "rack",
            getattr(
                self.instance,
                "rack",
                None,
            ),
        )

        if rack and branch and rack.branch_id != branch.id:
            raise serializers.ValidationError(
                {"rack": ("Selected rack does not belong " "to the selected branch.")}
            )

        return attrs

    def validate_barcode(self, value):
        """
        Empty barcode values are stored as NULL.

        PostgreSQL allows multiple NULL values in a unique column,
        but it does not allow multiple empty strings.
        """
        if value is None:
            return None

        normalized_value = str(value).strip()

        if not normalized_value:
            return None

        queryset = Product.objects.filter(barcode=normalized_value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A product with this barcode already exists."
            )

        return normalized_value

    def validate_variants(
        self,
        variants,
    ):
        has_variants = self.initial_data.get("has_variants")

        has_variants = str(has_variants).lower() in {
            "true",
            "1",
            "yes",
        }

        if has_variants:
            if not variants:
                raise serializers.ValidationError("Add at least one attribute variant.")

            for index, variant in enumerate(variants):
                if not variant.get("attributes"):
                    raise serializers.ValidationError(
                        {
                            index: {
                                "attributes": ("At least one attribute " "is required.")
                            }
                        }
                    )

        request = self.context.get("request")
        user = getattr(request, "user", None)
        is_admin = bool(
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or getattr(getattr(user, "role", None), "code", "") == "ADMIN"
            )
        )
        if not is_admin:
            for variant in variants:
                if int(variant.get("initial_restricted_stock", 0) or 0) > 0:
                    raise serializers.ValidationError(
                        "Only an administrator can enter initial restricted stock."
                    )
                variant.pop("initial_restricted_stock", None)

        return variants

    @staticmethod
    def _normalize_barcode(
        validated_data,
    ):
        """
        Defensive normalization for create and update.

        This protects the database even when serializer field
        validation is bypassed by custom logic.
        """
        if "barcode" not in validated_data:
            return validated_data

        barcode = validated_data.get("barcode")

        if barcode is None:
            validated_data["barcode"] = None
            return validated_data

        barcode = str(barcode).strip()

        validated_data["barcode"] = barcode if barcode else None

        return validated_data

    def _sync_variants(
        self,
        product,
        variants_data,
    ):
        self._stock_targets = {}
        existing = {variant.id: variant for variant in product.variants.all()}

        retained_ids = []

        if not product.has_variants:
            base_data = variants_data[0] if variants_data else {}

            base = product.variants.filter(is_base=True).first()

            if not base:
                base = ProductVariant(
                    product=product,
                    is_base=True,
                )

            base.attributes = {}

            initial_regular = base_data.pop("initial_regular_stock", None)
            initial_restricted = base_data.pop("initial_restricted_stock", None)
            base.available_qty = int(initial_regular or 0) + int(
                initial_restricted or 0
            )

            base.purchase_price = base_data.get("purchase_price") or None

            base.retail_price = base_data.get("retail_price") or 0

            base.wholesale_price = base_data.get("wholesale_price") or 0

            base.minimum_selling_price = base_data.get("minimum_selling_price") or 0

            base.is_active = True

            base.save()
            self._stock_targets[base.id] = {
                "regular": initial_regular,
                "restricted": initial_restricted,
            }

            product.variants.exclude(id=base.id).delete()

            return

        product.variants.filter(is_base=True).delete()

        for source_variant_data in variants_data:
            variant_data = dict(source_variant_data)

            variant_id = variant_data.pop(
                "id",
                None,
            )

            variant_data["is_base"] = False

            initial_regular = variant_data.pop("initial_regular_stock", None)
            initial_restricted = variant_data.pop("initial_restricted_stock", None)
            variant_data["available_qty"] = int(initial_regular or 0) + int(
                initial_restricted or 0
            )

            variant_data["purchase_price"] = variant_data.get("purchase_price") or None

            variant_data["retail_price"] = variant_data.get("retail_price") or 0

            variant_data["wholesale_price"] = variant_data.get("wholesale_price") or 0

            variant_data["minimum_selling_price"] = (
                variant_data.get("minimum_selling_price") or 0
            )

            if variant_id and variant_id in existing:
                variant = existing[variant_id]

                for (
                    field,
                    field_value,
                ) in variant_data.items():
                    setattr(
                        variant,
                        field,
                        field_value,
                    )

                variant.save()

            else:
                variant = ProductVariant.objects.create(
                    product=product,
                    **variant_data,
                )

            self._stock_targets[variant.id] = {
                "regular": initial_regular,
                "restricted": initial_restricted,
            }
            retained_ids.append(variant.id)

        product.variants.exclude(id__in=retained_ids).delete()

    def _sync_branch_stock(
        self,
        product,
        *,
        reference_type,
    ):
        """
        Synchronize the quantity entered in the product form
        with the actual ProductStock record.

        Every quantity difference is written through adjust_stock()
        so the stock movement audit history is preserved.
        """
        if not product.branch_id:
            return

        request = self.context.get("request")

        user = request.user if (request and request.user.is_authenticated) else None

        active_variants = product.variants.filter(is_active=True)

        for variant in active_variants:
            stock_variant = variant if product.has_variants else None

            targets = getattr(self, "_stock_targets", {}).get(
                variant.id,
                {
                    "regular": int(variant.available_qty or 0),
                    "restricted": 0,
                },
            )
            desired_regular = targets.get("regular")
            desired_restricted = targets.get("restricted")

            stock, _ = ProductStock.objects.get_or_create(
                product=product,
                branch=product.branch,
                variant=stock_variant,
                defaults={
                    "current_stock": 0,
                    "regular_quantity": 0,
                    "restricted_quantity": 0,
                    "reserved_stock": 0,
                    "reserved_regular_quantity": 0,
                    "reserved_restricted_quantity": 0,
                    "reorder_level": product.reorder_level,
                },
            )

            if desired_regular is None:
                desired_regular = int(stock.regular_quantity or 0)
            else:
                desired_regular = int(desired_regular or 0)

            if desired_restricted is None:
                desired_restricted = int(stock.restricted_quantity or 0)
            else:
                desired_restricted = int(desired_restricted or 0)

            regular_difference = desired_regular - int(stock.regular_quantity or 0)
            restricted_difference = desired_restricted - int(
                stock.restricted_quantity or 0
            )

            if regular_difference:
                adjust_stock(
                    product=product,
                    variant=stock_variant,
                    branch=product.branch,
                    quantity=regular_difference,
                    movement_type=(
                        "OPENING"
                        if reference_type == "PRODUCT_CREATE"
                        else "ADJUSTMENT"
                    ),
                    stock_classification="REGULAR",
                    performed_by=user,
                    reference_type=reference_type,
                    reference_id=product.id,
                    remarks="Initial regular stock from product form.",
                )

            if restricted_difference:
                adjust_stock(
                    product=product,
                    variant=stock_variant,
                    branch=product.branch,
                    quantity=restricted_difference,
                    movement_type=(
                        "PURCHASE_RESTRICTED"
                        if reference_type == "PRODUCT_CREATE"
                        else "ADJUSTMENT"
                    ),
                    stock_classification="RESTRICTED",
                    performed_by=user,
                    reference_type=reference_type,
                    reference_id=product.id,
                    remarks="Initial restricted stock from product form.",
                )

            if stock.reorder_level != product.reorder_level:
                stock.reorder_level = product.reorder_level
                stock.save(update_fields=["reorder_level", "updated_at"])

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        validated_data = self._normalize_barcode(validated_data)

        variants_data = validated_data.pop(
            "variants",
            [],
        )

        product = super().create(validated_data)

        self._sync_variants(
            product,
            variants_data,
        )

        self._sync_branch_stock(
            product,
            reference_type=("PRODUCT_CREATE"),
        )

        return product

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        validated_data = self._normalize_barcode(validated_data)

        variants_supplied = "variants" in validated_data

        variants_data = validated_data.pop(
            "variants",
            [],
        )

        product = super().update(
            instance,
            validated_data,
        )

        if variants_supplied or not product.has_variants:
            self._sync_variants(
                product,
                variants_data,
            )

        self._sync_branch_stock(
            product,
            reference_type=("PRODUCT_EDIT"),
        )

        return product


class ProductStockSerializer(serializers.ModelSerializer):
    available_stock = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()
    available_regular_quantity = serializers.SerializerMethodField()
    available_restricted_quantity = serializers.SerializerMethodField()
    total_available_quantity = serializers.SerializerMethodField()
    inventory_value_excluding_vat = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    recoverable_vat_value = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    capitalized_vat_value = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    total_inventory_value = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    regular_stock_value = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    restricted_stock_value = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )
    variant_label = serializers.SerializerMethodField()

    class Meta:
        model = ProductStock
        fields = "__all__"

    def _annotated_or_property(self, obj, annotated_name, property_name):
        value = getattr(obj, annotated_name, None)
        if value is None:
            value = getattr(obj, property_name)
        return max(0, int(value or 0))

    def get_total_quantity(self, obj):
        return self._annotated_or_property(
            obj,
            "total_quantity_db",
            "total_quantity",
        )

    def get_available_regular_quantity(self, obj):
        return self._annotated_or_property(
            obj,
            "available_regular_db",
            "available_regular_quantity",
        )

    def get_available_restricted_quantity(self, obj):
        return self._annotated_or_property(
            obj,
            "available_restricted_db",
            "available_restricted_quantity",
        )

    def get_total_available_quantity(self, obj):
        return self._annotated_or_property(
            obj,
            "total_available_db",
            "total_available_quantity",
        )

    def get_available_stock(self, obj):
        # Keep the legacy API key while calculating from classified balances.
        return self.get_total_available_quantity(obj)

    def get_variant_label(self, obj):
        return variant_label(obj.variant)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        from apps.common.sensitive_permissions import can_view_restricted

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not can_view_restricted(user):
            for field in (
                "restricted_quantity",
                "reserved_restricted_quantity",
                "available_restricted_quantity",
                "total_quantity",
                "total_available_quantity",
            ):
                data.pop(field, None)

            regular_available = self.get_available_regular_quantity(instance)
            data["available_quantity"] = regular_available
            data["available_stock"] = regular_available

        return data


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )
    variant_label = serializers.SerializerMethodField()
    movement_type_display = serializers.CharField(
        source="get_movement_type_display",
        read_only=True,
    )
    performed_by_name = serializers.SerializerMethodField()
    vat_treatment_display = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = "__all__"

    def get_variant_label(self, obj):
        return variant_label(obj.variant)

    def get_vat_treatment_display(self, obj):
        return str(obj.vat_treatment or "OUT_OF_SCOPE").replace("_", " ").title()

    def get_performed_by_name(self, obj):
        if not obj.performed_by:
            return None

        return (
            getattr(
                obj.performed_by,
                "full_name",
                None,
            )
            or getattr(
                obj.performed_by,
                "email",
                None,
            )
            or str(obj.performed_by)
        )


class StockAdjustmentSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )
    variant_label = serializers.SerializerMethodField()
    signed_quantity = serializers.IntegerField(
        read_only=True,
    )
    approved_by_name = serializers.SerializerMethodField()
    adjusted_at = serializers.DateTimeField(
        source="created_at",
        read_only=True,
    )
    vat_treatment_display = serializers.SerializerMethodField()
    adjustment_reason_display = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "adjustment_number",
            "branch",
            "branch_name",
            "branch_code",
            "product",
            "product_name",
            "sku",
            "variant",
            "variant_label",
            "adjusted_at",
            "vat_treatment_display",
            "adjustment_reason_display",
            "stock_classification",
            "adjustment_type",
            "quantity",
            "signed_quantity",
            "reason",
            "remarks",
            "status",
            "approved_by",
            "approved_by_name",
            "current_quantity",
            "actual_quantity_counted",
            "quantity_difference",
            "unit_cost_excluding_vat",
            "vat_treatment",
            "vat_percentage",
            "recoverable_vat_amount",
            "non_recoverable_vat_amount",
            "capitalized_adjustment_value",
            "value_before",
            "value_after",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = [
            "adjustment_number",
            "branch_name",
            "branch_code",
            "product_name",
            "sku",
            "variant_label",
            "adjusted_at",
            "vat_treatment_display",
            "adjustment_reason_display",
            "signed_quantity",
            "status",
            "approved_by",
            "approved_by_name",
            "current_quantity",
            "actual_quantity_counted",
            "quantity_difference",
            "unit_cost_excluding_vat",
            "vat_treatment",
            "vat_percentage",
            "recoverable_vat_amount",
            "non_recoverable_vat_amount",
            "capitalized_adjustment_value",
            "value_before",
            "value_after",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]

    def validate(self, attrs):
        product = attrs.get("product")
        variant = attrs.get("variant")
        adjustment_type = str(attrs.get("adjustment_type") or "").strip().upper()
        quantity = attrs.get("quantity")
        classification = (
            str(attrs.get("stock_classification") or "REGULAR").strip().upper()
        )

        if variant and product and variant.product_id != product.id:
            raise serializers.ValidationError(
                {"variant": ("Selected variant does not belong to the product.")}
            )

        if product and product.has_variants and not variant:
            raise serializers.ValidationError(
                {"variant": ("Select an attribute combination for this product.")}
            )

        if adjustment_type not in {"ADD", "DEDUCT"}:
            raise serializers.ValidationError(
                {"adjustment_type": ("Select Increase or Decrease.")}
            )

        if quantity is None or int(quantity) <= 0:
            raise serializers.ValidationError(
                {"quantity": ("Quantity must be greater than zero.")}
            )

        if classification not in {
            "REGULAR",
            "RESTRICTED",
        }:
            raise serializers.ValidationError(
                {"stock_classification": ("Select Regular or Restricted stock.")}
            )

        attrs["adjustment_type"] = adjustment_type
        attrs["stock_classification"] = classification
        return attrs

    def get_variant_label(self, obj):
        return variant_label(obj.variant) if obj.variant_id else ""

    def get_approved_by_name(self, obj):
        user = getattr(obj, "approved_by", None)
        if not user:
            return ""

        full_name = ""
        if hasattr(user, "get_full_name"):
            full_name = user.get_full_name() or ""

        return full_name or getattr(user, "username", "") or getattr(user, "email", "")

    def get_vat_treatment_display(self, obj):
        display_method = getattr(
            obj,
            "get_vat_treatment_display",
            None,
        )

        if callable(display_method):
            return display_method()

        return str(getattr(obj, "vat_treatment", "") or "").replace("_", " ").title()

    def get_adjustment_reason_display(self, obj):
        display_method = getattr(
            obj,
            "get_adjustment_reason_display",
            None,
        )

        if callable(display_method):
            return display_method()

        return (
            str(getattr(obj, "adjustment_reason", "") or "").replace("_", " ").title()
        )
