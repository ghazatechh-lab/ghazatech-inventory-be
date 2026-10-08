import json

from django.db import transaction
from rest_framework import serializers

from apps.branch_data.services import database_alias_for_branch
from apps.branch_data.physical import require_physical_branch, request_active_branch, is_physical_branch
from apps.branches.models import Branch

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

    def validate(self, attrs):
        branch = attrs.get("branch") or getattr(self.instance, "branch", None)
        active_branch = request_active_branch(self.context.get("request"))
        if active_branch and is_physical_branch(active_branch) and self.instance is None:
            branch = active_branch
            attrs["branch"] = active_branch
        require_physical_branch(branch, field="branch")
        return attrs


class ProductVariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    racks = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Rack.objects.filter(is_active=True),
    )
    rack_details = serializers.SerializerMethodField()

    # Used only while creating or editing a product. The value initializes the
    # ProductStock row for the selected branch and is not stored separately on
    # ProductVariant.
    initial_stock = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=0,
    )

    available_qty = serializers.IntegerField(read_only=True)
    current_stock = serializers.SerializerMethodField()
    reserved_stock = serializers.SerializerMethodField()
    available_stock = serializers.SerializerMethodField()

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
            "racks",
            "rack_details",
            "display_name",
            "initial_stock",
            "available_qty",
            "current_stock",
            "reserved_stock",
            "available_stock",
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
            "rack_details",
            "available_qty",
            "current_stock",
            "reserved_stock",
            "available_stock",
            "is_base",
            "created_at",
            "updated_at",
        ]

    def get_display_name(self, obj):
        return variant_label(obj)

    def get_rack_details(self, obj):
        return [
            {
                "id": rack.id,
                "rack_code": rack.rack_code,
                "rack_name": rack.rack_name,
                "branch": rack.branch_id,
            }
            for rack in obj.racks.all().order_by("rack_code")
        ]

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

    def get_current_stock(self, obj):
        stock = self._stock(obj)
        return int(stock.current_stock or 0) if stock else 0

    def get_reserved_stock(self, obj):
        stock = self._stock(obj)
        return int(stock.reserved_stock or 0) if stock else 0

    def get_available_stock(self, obj):
        stock = self._stock(obj)
        return int(stock.available_stock) if stock else 0

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["available_qty"] = self.get_available_stock(instance)
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
        branch_id = get_requested_branch_id(self) or obj.branch_id
        racks = Rack.objects.filter(product_variants__product=obj).distinct()

        requested_branch = None
        if branch_id:
            requested_branch = Branch.objects.filter(pk=branch_id).first()

        if requested_branch and requested_branch.branch_code == "BR03":
            racks = racks.filter(branch__branch_code__in=["BR01", "BR02"])
        elif branch_id:
            racks = racks.filter(branch_id=branch_id)

        codes = list(racks.order_by("rack_code").values_list("rack_code", flat=True))
        if codes:
            return ", ".join(codes)

        # Backward-compatible fallback for products created before variant racks.
        if obj.rack_id:
            if not requested_branch:
                return obj.rack.rack_code
            if requested_branch.branch_code == "BR03" and obj.rack.branch.branch_code in {"BR01", "BR02"}:
                return obj.rack.rack_code
            if obj.rack.branch_id == requested_branch.id:
                return obj.rack.rack_code
        return None

    def get_product_image_url(self, obj):
        if not obj.product_image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.product_image.url)

        return obj.product_image.url

    def get_total_available_qty(self, obj):
        branch_id = get_requested_branch_id(self)

        if not branch_id:
            # Stock is physically stored in the branch databases. In an
            # unscoped request, aggregate both physical branches.
            target_branches = list(
                Branch.objects.filter(branch_code__in=["BR01", "BR02"])
            )
        else:
            requested_branch = Branch.objects.filter(pk=branch_id).first()
            if not requested_branch:
                return 0

            if requested_branch.branch_code == "BR03":
                target_branches = list(
                    Branch.objects.filter(branch_code__in=["BR01", "BR02"])
                )
            else:
                target_branches = [requested_branch]

        total = 0
        for branch in target_branches:
            using = database_alias_for_branch(branch.id)
            stocks = ProductStock.objects.using(using).filter(
                product_id=obj.id,
                branch_id=branch.id,
            )
            total += sum(max(0, stock.available_stock) for stock in stocks)

        return total

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

        active_branch = request_active_branch(self.context.get("request"))
        if active_branch and is_physical_branch(active_branch) and self.instance is None:
            branch = active_branch
            attrs["branch"] = active_branch
        require_physical_branch(branch, field="branch")

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
                {"rack": "Selected rack does not belong to the selected branch."}
            )

        sku = str(
            attrs.get(
                "sku",
                getattr(self.instance, "sku", ""),
            )
            or ""
        ).strip()

        if not sku:
            raise serializers.ValidationError({"sku": "SKU is required."})

        sku_queryset = Product.objects.filter(
            sku__iexact=sku,
            branch=branch,
            is_deleted=False,
        )

        if self.instance:
            sku_queryset = sku_queryset.exclude(pk=self.instance.pk)

        if sku_queryset.exists():
            raise serializers.ValidationError(
                {
                    "sku": (
                        "A product with this SKU already exists "
                        "in the selected branch."
                    )
                }
            )

        barcode = attrs.get("barcode", getattr(self.instance, "barcode", None))
        if barcode:
            barcode_queryset = Product.objects.filter(
                branch=branch, barcode=barcode, is_deleted=False
            )
            if self.instance:
                barcode_queryset = barcode_queryset.exclude(pk=self.instance.pk)
            if barcode_queryset.exists():
                raise serializers.ValidationError({
                    "barcode": "A product with this barcode already exists in the selected branch."
                })

        attrs["sku"] = sku

        compatible_models = str(
            attrs.get(
                "compatible_models",
                getattr(self.instance, "compatible_models", ""),
            )
            or ""
        ).strip()
        attrs["compatible_models"] = compatible_models or "All Models"

        tax_treatment = str(
            attrs.get(
                "tax_treatment",
                getattr(self.instance, "tax_treatment", "VAT"),
            )
            or "VAT"
        ).upper()

        if tax_treatment not in {"VAT", "ZERO_VAT", "NON_VAT"}:
            raise serializers.ValidationError(
                {"tax_treatment": "Select VAT, Zero VAT, or Non-VAT."}
            )

        attrs["tax_treatment"] = tax_treatment
        if tax_treatment == "VAT":
            attrs["vat_rate"] = 5
        else:
            # ZERO_VAT remains a taxable zero-rated supply, while NON_VAT is
            # outside VAT. Both produce a zero tax amount.
            attrs["vat_rate"] = 0
            attrs["vat_inclusive"] = False

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

        return normalized_value

    def validate_variants(self, variants):
        has_variants = str(self.initial_data.get("has_variants", "")).lower() in {
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
                        {index: {"attributes": "At least one attribute is required."}}
                    )

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

    def _sync_variants(self, product, variants_data):
        self._stock_targets = {}
        existing = {variant.id: variant for variant in product.variants.all()}
        retained_ids = []

        if not product.has_variants:
            base_data = dict(variants_data[0]) if variants_data else {}
            base = product.variants.filter(is_base=True).first()

            if not base:
                base = ProductVariant(product=product, is_base=True)

            initial_stock = base_data.pop("initial_stock", None)
            variant_racks = base_data.pop("racks", [])
            base.attributes = {}
            base.available_qty = int(initial_stock or 0)
            base.purchase_price = base_data.get("purchase_price") or None
            base.retail_price = base_data.get("retail_price") or 0
            base.wholesale_price = base_data.get("wholesale_price") or 0
            base.minimum_selling_price = base_data.get("minimum_selling_price") or 0
            base.is_active = True
            base.save()
            if variant_racks is not None:
                invalid_racks = [
                    rack
                    for rack in variant_racks
                    if product.branch_id and rack.branch_id != product.branch_id
                ]
                if invalid_racks:
                    raise serializers.ValidationError(
                        {
                            "variants": "All selected racks must belong to the product branch."
                        }
                    )
                base.racks.set(variant_racks)

            self._stock_targets[base.id] = initial_stock
            product.variants.exclude(id=base.id).delete()
            return

        product.variants.filter(is_base=True).delete()

        for source_variant_data in variants_data:
            variant_data = dict(source_variant_data)
            variant_id = variant_data.pop("id", None)
            initial_stock = variant_data.pop("initial_stock", None)
            variant_racks = variant_data.pop("racks", [])

            variant_data["is_base"] = False
            variant_data["available_qty"] = int(initial_stock or 0)
            variant_data["purchase_price"] = variant_data.get("purchase_price") or None
            variant_data["retail_price"] = variant_data.get("retail_price") or 0
            variant_data["wholesale_price"] = variant_data.get("wholesale_price") or 0
            variant_data["minimum_selling_price"] = (
                variant_data.get("minimum_selling_price") or 0
            )

            if variant_id and variant_id in existing:
                variant = existing[variant_id]
                for field, field_value in variant_data.items():
                    setattr(variant, field, field_value)
                variant.save()
            else:
                variant = ProductVariant.objects.create(
                    product=product,
                    **variant_data,
                )

            if variant_racks is not None:
                invalid_racks = [
                    rack
                    for rack in variant_racks
                    if product.branch_id and rack.branch_id != product.branch_id
                ]
                if invalid_racks:
                    raise serializers.ValidationError(
                        {
                            "variants": "All selected racks must belong to the product branch."
                        }
                    )
                variant.racks.set(variant_racks)

            self._stock_targets[variant.id] = initial_stock
            retained_ids.append(variant.id)

        product.variants.exclude(id__in=retained_ids).delete()

    def _mirror_catalog_to_branch_db(self, product):
        """Mirror shared catalog rows required by physical stock FKs.

        ``default`` remains authoritative for catalog editing, while VAT and
        NON_VAT keep same-PK mirrors so ProductStock/StockMovement foreign keys
        are valid in the physical inventory database.
        """
        if not product.branch_id:
            return "default"

        using = database_alias_for_branch(product.branch_id)
        if using == "default":
            return using

        def mirror_simple(instance, model, fields):
            defaults = {field: getattr(instance, field) for field in fields}
            model.objects.using(using).update_or_create(
                pk=instance.pk, defaults=defaults
            )

        mirror_simple(product.brand, Brand, ["name", "is_active"])
        mirror_simple(product.category, Category, ["name", "is_active"])

        rack_ids = set()
        if product.rack_id:
            rack_ids.add(product.rack_id)
        for variant in product.variants.all():
            rack_ids.update(variant.racks.values_list("id", flat=True))

        for rack in Rack.objects.using("default").filter(id__in=rack_ids):
            Rack.objects.using(using).update_or_create(
                pk=rack.pk,
                defaults={
                    "branch_id": rack.branch_id,
                    "rack_code": rack.rack_code,
                    "rack_name": rack.rack_name,
                    "is_active": rack.is_active,
                },
            )

        supplier_id = product.supplier_id
        if supplier_id:
            from apps.suppliers.models import Supplier
            if not Supplier.objects.using(using).filter(pk=supplier_id).exists():
                supplier_id = None

        Product.objects.using(using).update_or_create(
            pk=product.pk,
            defaults={
                "product_name": product.product_name,
                "sku": product.sku,
                "barcode": product.barcode,
                "brand_id": product.brand_id,
                "category_id": product.category_id,
                "branch_id": product.branch_id,
                "rack_id": product.rack_id,
                "has_variants": product.has_variants,
                "compatible_models": product.compatible_models,
                "condition": product.condition,
                "unit": product.unit,
                "tax_treatment": product.tax_treatment,
                "vat_inclusive": product.vat_inclusive,
                "vat_rate": product.vat_rate,
                "supplier_id": supplier_id,
                "description": product.description,
                "product_image": product.product_image.name if product.product_image else None,
                "warranty_period_days": product.warranty_period_days,
                "reorder_level": product.reorder_level,
                "is_active": product.is_active,
                "is_deleted": product.is_deleted,
                "deleted_at": product.deleted_at,
                "deleted_by_id": None,
            },
        )

        mirrored_variant_ids = []
        for variant in product.variants.all():
            mirrored, _ = ProductVariant.objects.using(using).update_or_create(
                pk=variant.pk,
                defaults={
                    "product_id": product.pk,
                    "attributes": variant.attributes,
                    "available_qty": variant.available_qty,
                    "purchase_price": variant.purchase_price,
                    "retail_price": variant.retail_price,
                    "wholesale_price": variant.wholesale_price,
                    "minimum_selling_price": variant.minimum_selling_price,
                    "is_base": variant.is_base,
                    "is_active": variant.is_active,
                },
            )
            mirrored.racks.set(list(variant.racks.values_list("id", flat=True)))
            mirrored_variant_ids.append(variant.pk)

        ProductVariant.objects.using(using).filter(product_id=product.pk).exclude(
            pk__in=mirrored_variant_ids
        ).delete()
        return using

    def _sync_branch_stock(self, product, *, reference_type):
        """Synchronize product-form quantity with the branch stock ledger."""
        if not product.branch_id:
            return

        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None

        for variant in product.variants.filter(is_active=True):
            stock_variant = variant if product.has_variants else None
            desired_stock = getattr(self, "_stock_targets", {}).get(variant.id)

            using = database_alias_for_branch(product.branch_id)
            stock, _ = ProductStock.objects.using(using).get_or_create(
                product_id=product.id,
                branch_id=product.branch_id,
                variant_id=(stock_variant.id if stock_variant else None),
                warehouse="",
                defaults={
                    "current_stock": 0,
                    "reserved_stock": 0,
                    "reorder_level": product.reorder_level,
                },
            )

            if desired_stock is None:
                desired_stock = int(stock.current_stock or 0)
            else:
                desired_stock = int(desired_stock or 0)

            difference = desired_stock - int(stock.current_stock or 0)

            if difference:
                adjust_stock(
                    product=product,
                    variant=stock_variant,
                    branch=product.branch,
                    quantity=difference,
                    movement_type=(
                        "OPENING"
                        if reference_type == "PRODUCT_CREATE"
                        else "ADJUSTMENT"
                    ),
                    performed_by=user,
                    reference_type=reference_type,
                    reference_id=product.id,
                    remarks="Stock quantity updated from product form.",
                    unit_cost=(variant.purchase_price if difference > 0 else None),
                    vat_treatment=product.tax_treatment,
                    vat_percentage=product.vat_rate,
                    vat_inclusive=product.vat_inclusive,
                )

            if stock.reorder_level != product.reorder_level:
                stock.reorder_level = product.reorder_level
                stock.save(using=using, update_fields=["reorder_level", "updated_at"])

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

        self._mirror_catalog_to_branch_db(product)
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

        self._mirror_catalog_to_branch_db(product)
        self._sync_branch_stock(
            product,
            reference_type=("PRODUCT_EDIT"),
        )

        return product


class ProductStockSerializer(serializers.ModelSerializer):
    available_stock = serializers.IntegerField(read_only=True)
    total_quantity = serializers.IntegerField(read_only=True)
    total_available_quantity = serializers.IntegerField(read_only=True)
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
    rack_code = serializers.SerializerMethodField()
    rack_name = serializers.SerializerMethodField()
    variant_label = serializers.SerializerMethodField()
    tax_treatment = serializers.CharField(
        source="product.tax_treatment",
        read_only=True,
    )
    vat_rate = serializers.DecimalField(
        source="product.vat_rate",
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = ProductStock
        fields = "__all__"

    def get_variant_label(self, obj):
        return variant_label(obj.variant)

    def _racks(self, obj):
        variant = obj.variant
        if variant is None and not obj.product.has_variants:
            variant = obj.product.variants.filter(is_base=True).first()
        if variant:
            return list(variant.racks.filter(branch=obj.branch).order_by("rack_code"))
        return []

    def get_rack_code(self, obj):
        racks = self._racks(obj)
        if racks:
            return ", ".join(rack.rack_code for rack in racks)
        return obj.product.rack.rack_code if obj.product.rack_id else ""

    def get_rack_name(self, obj):
        racks = self._racks(obj)
        if racks:
            return ", ".join(filter(None, (rack.rack_name for rack in racks)))
        return obj.product.rack.rack_name if obj.product.rack_id else ""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["available_quantity"] = int(instance.available_stock)
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
        instance = self.instance

        product = attrs.get(
            "product",
            getattr(instance, "product", None),
        )
        variant = attrs.get(
            "variant",
            getattr(instance, "variant", None),
        )
        branch = attrs.get(
            "branch",
            getattr(instance, "branch", None),
        )
        adjustment_type = (
            str(
                attrs.get(
                    "adjustment_type",
                    getattr(instance, "adjustment_type", ""),
                )
                or ""
            )
            .strip()
            .upper()
        )
        quantity = attrs.get(
            "quantity",
            getattr(instance, "quantity", None),
        )
        reason = str(
            attrs.get(
                "reason",
                getattr(instance, "reason", ""),
            )
            or ""
        ).strip()

        errors = {}

        if not branch:
            errors["branch"] = "Branch is required."
        elif not is_physical_branch(branch):
            errors["branch"] = "Select Branch 1 or Branch 2. Branch 3 cannot own stock adjustments."

        if not product:
            errors["product"] = "Product is required."

        if variant and product and variant.product_id != product.id:
            errors["variant"] = "Selected variant does not belong to the product."

        if product and product.has_variants and not variant:
            errors["variant"] = "Select an attribute combination for this product."

        if adjustment_type not in {"ADD", "DEDUCT"}:
            errors["adjustment_type"] = "Select Increase or Decrease."

        try:
            parsed_quantity = int(quantity)
        except (TypeError, ValueError):
            parsed_quantity = 0

        if parsed_quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if not reason:
            errors["reason"] = "Reason is required."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["adjustment_type"] = adjustment_type

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
