import json
import secrets

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.branch_data.services import database_alias_for_branch
from apps.branches.models import Branch

from .services import adjust_stock
from .physical_catalog import (
    ensure_product_catalog_in_database,
    physical_product_supplier_id,
    require_physical_branch,
    validate_supplier_for_branch,
    validate_product_sku_for_branch,
    physical_branch_label,
    resolve_physical_product,
    resolve_variant_in_physical_database,
    ensure_variant_in_physical_database,
)

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
    context = serializer.context if hasattr(serializer, "context") else {}
    source_branch_id = context.get("source_branch_id")
    if source_branch_id is not None:
        return int(source_branch_id)
    request = context.get("request")
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
        # Consolidated rows retain their tenant connection; do not let the
        # relation manager route the join query to a legacy public schema.
        alias = obj._state.db or "default"
        through = ProductVariant.racks.through
        rack_ids = list(
            through.objects.using(alias)
            .filter(productvariant_id=obj.pk)
            .values_list("rack_id", flat=True)
        )
        return [
            {
                "id": rack.id,
                "rack_code": rack.rack_code,
                "rack_name": rack.rack_name,
                "branch": rack.branch_id,
            }
            for rack in Rack.objects.using(alias)
            .filter(pk__in=rack_ids)
            .order_by("rack_code")
        ]

    def _stock(self, obj):
        alias = obj._state.db or "default"
        # ForeignKey descriptor `obj.product` can re-route to the legacy VAT
        # public schema, where this tenant product ID does not exist.
        product = (
            Product.objects.using(alias)
            .only("id", "branch_id", "has_variants")
            .get(pk=obj.product_id)
        )
        branch_id = (
            self.context.get("source_branch_id")
            or get_requested_branch_id(self)
            or product.branch_id
        )
        if not branch_id:
            return None
        stock_variant_id = obj.pk if product.has_variants else None
        return (
            ProductStock.objects.using(alias)
            .filter(
                product_id=obj.product_id,
                variant_id=stock_variant_id,
                branch_id=branch_id,
            )
            .first()
        )

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


def _is_product_sku_integrity_error(exc):
    cause = getattr(exc, "__cause__", None)
    diag = getattr(cause, "diag", None)
    constraint = getattr(diag, "constraint_name", "") if diag else ""
    return constraint in {
        "unique_product_sku_per_branch",
        "unique_unassigned_product_sku",
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
    supplier = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    supplier_name = serializers.SerializerMethodField()

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
            if (
                requested_branch.branch_code == "BR03"
                and obj.rack.branch.branch_code in {"BR01", "BR02"}
            ):
                return obj.rack.rack_code
            if obj.rack.branch_id == requested_branch.id:
                return obj.rack.rack_code
        return None

    def _physical_supplier_id(self, obj):
        return physical_product_supplier_id(obj, getattr(obj, "branch_id", None))

    def get_supplier_name(self, obj):
        supplier_id = self._physical_supplier_id(obj)
        if not supplier_id or not obj.branch_id:
            return None
        branch = require_physical_branch(obj.branch_id)
        using = database_alias_for_branch(branch.id)
        from apps.suppliers.models import Supplier

        return (
            Supplier.objects.using(using)
            .filter(pk=supplier_id, branch_id=branch.id, is_deleted=False)
            .values_list("supplier_name", flat=True)
            .first()
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["supplier"] = self._physical_supplier_id(instance)
        return data

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
                Branch.objects.filter(branch_code__in=["BR01", "BR02", "CONSOLIDATED"])
            )
        else:
            requested_branch = Branch.objects.filter(pk=branch_id).first()
            if not requested_branch:
                return 0

            if requested_branch.branch_code == "BR03":
                target_branches = list(
                    Branch.objects.filter(branch_code__in=["BR01", "BR02", "CONSOLIDATED"])
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

        rack = attrs.get(
            "rack",
            getattr(
                self.instance,
                "rack",
                None,
            ),
        )

        branch = require_physical_branch(branch)

        if (
            self.instance
            and self.instance.branch_id
            and self.instance.branch_id != branch.id
        ):
            raise serializers.ValidationError(
                {
                    "branch": (
                        "An existing product cannot be moved between physical branches. "
                        "Create a new product in the target branch instead."
                    )
                }
            )

        supplier_supplied = "supplier" in attrs
        if supplier_supplied:
            supplier_id = attrs.get("supplier")
        elif self.instance:
            supplier_id = physical_product_supplier_id(self.instance, branch)
        else:
            supplier_id = None

        if supplier_id not in (None, "", 0, "0"):
            supplier = validate_supplier_for_branch(
                supplier_id=supplier_id,
                branch=branch,
                required=True,
            )
            attrs["supplier"] = supplier.pk
        elif supplier_supplied:
            attrs["supplier"] = None

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

        # Validate both the authoritative/default catalog and the target physical
        # database before saving. This keeps PostgreSQL unique constraints as a
        # last line of defense rather than the user-facing validation path.
        sku_queryset = Product.objects.using("default").filter(
            sku__iexact=sku,
            branch_id=branch.id,
            is_deleted=False,
        )

        if self.instance:
            sku_queryset = sku_queryset.exclude(pk=self.instance.pk)

        if sku_queryset.exists():
            raise serializers.ValidationError(
                {"sku": f"{sku} already exists in {physical_branch_label(branch)}."}
            )

        attrs["sku"] = validate_product_sku_for_branch(
            branch=branch,
            sku=sku,
            current_product_id=(self.instance.pk if self.instance else None),
            original_sku=(self.instance.sku if self.instance else None),
        )

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

        queryset = Product.objects.filter(barcode=normalized_value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A product with this barcode already exists."
            )

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

    def _mirror_catalog_to_branch_db(
        self, product, *, supplier_id=None, original_sku=None
    ):
        return ensure_product_catalog_in_database(
            product,
            product.branch,
            supplier_id=supplier_id,
            validate_supplier=supplier_id not in (None, "", 0, "0"),
            original_sku=original_sku,
        )

    def _sync_branch_stock(self, product, *, reference_type, physical_product):
        """Use physical database IDs for physical stock and ledger mutations."""
        if not product.branch_id:
            return
        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None
        using = database_alias_for_branch(product.branch_id)
        for variant in product.variants.filter(is_active=True):
            physical_variant = (
                resolve_variant_in_physical_database(
                    variant, physical_product, product.branch
                )
                if product.has_variants
                else None
            )
            if product.has_variants and physical_variant is None:
                # New variants may have been saved in the shared catalog but
                # not yet mirrored in the physical DB. Repair only beneath the
                # SKU-verified physical product; never match by numeric ID.
                physical_variant = ensure_variant_in_physical_database(
                    variant, physical_product, product.branch
                )
            desired_stock = getattr(self, "_stock_targets", {}).get(variant.id)
            stock, _ = ProductStock.objects.using(using).get_or_create(
                product_id=physical_product.pk,
                branch_id=product.branch_id,
                variant_id=(physical_variant.pk if physical_variant else None),
                warehouse="",
                defaults={
                    "current_stock": 0,
                    "reserved_stock": 0,
                    "reorder_level": product.reorder_level,
                },
            )
            desired_stock = (
                int(stock.current_stock or 0)
                if desired_stock is None
                else int(desired_stock or 0)
            )
            difference = desired_stock - int(stock.current_stock or 0)
            if difference:
                adjust_stock(
                    product=physical_product,
                    variant=physical_variant,
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
                    unit_cost=variant.purchase_price if difference > 0 else None,
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

        # Assign a scan-friendly Code 39 value on creation, not on edit.
        # Keep manually-entered and existing barcodes unchanged.
        if not validated_data.get("barcode"):
            for _ in range(10):
                candidate = "GHZ" + secrets.token_hex(6).upper()
                if not Product.objects.filter(barcode=candidate).exists():
                    validated_data["barcode"] = candidate
                    break
            else:
                raise serializers.ValidationError(
                    {"barcode": "Unable to generate a unique barcode. Please retry."}
                )

        variants_data = validated_data.pop(
            "variants",
            [],
        )
        supplier_id = validated_data.pop("supplier", None)

        # Supplier is branch-owned and must never be persisted as a FK on the
        # shared/default Product row. It is written only to the target physical
        # product mirror after same-database validation.
        try:
            with transaction.atomic(using="default"):
                product = super().create(validated_data)
        except IntegrityError as exc:
            if _is_product_sku_integrity_error(exc):
                branch = require_physical_branch(validated_data.get("branch"))
                sku = str(validated_data.get("sku") or "").strip()
                raise serializers.ValidationError(
                    {"sku": f"{sku} already exists in {physical_branch_label(branch)}."}
                ) from exc
            raise

        self._sync_variants(
            product,
            variants_data,
        )

        # A later stock error must roll back the physical catalog mirror too.
        # The outer default transaction already protects shared catalog writes.
        with transaction.atomic(using=database_alias_for_branch(product.branch_id)):
            physical_product = self._mirror_catalog_to_branch_db(
                product, supplier_id=supplier_id
            )
            self._sync_branch_stock(
                product,
                physical_product=physical_product,
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
        supplier_supplied = "supplier" in validated_data
        supplier_id = validated_data.pop("supplier", None)
        if not supplier_supplied:
            supplier_id = physical_product_supplier_id(instance, instance.branch_id)

        original_sku = instance.sku
        try:
            with transaction.atomic(using="default"):
                product = super().update(
                    instance,
                    validated_data,
                )
        except IntegrityError as exc:
            if _is_product_sku_integrity_error(exc):
                branch = require_physical_branch(
                    validated_data.get("branch", instance.branch_id)
                )
                sku = str(validated_data.get("sku", instance.sku) or "").strip()
                raise serializers.ValidationError(
                    {"sku": f"{sku} already exists in {physical_branch_label(branch)}."}
                ) from exc
            raise

        if variants_supplied or not product.has_variants:
            self._sync_variants(
                product,
                variants_data,
            )

        # A later stock error must roll back the physical catalog mirror too.
        # The outer default transaction already protects shared catalog writes.
        with transaction.atomic(using=database_alias_for_branch(product.branch_id)):
            physical_product = self._mirror_catalog_to_branch_db(
                product, supplier_id=supplier_id, original_sku=original_sku
            )
            self._sync_branch_stock(
                product,
                physical_product=physical_product,
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
        alias = obj._state.db or "default"
        variant_id = obj.variant_id
        if variant_id is None and not obj.product.has_variants:
            variant_id = (
                ProductVariant.objects.using(alias)
                .filter(product_id=obj.product_id, is_base=True)
                .values_list("id", flat=True)
                .first()
            )
        if not variant_id:
            return []
        rack_ids = (
            ProductVariant.racks.through.objects.using(alias)
            .filter(productvariant_id=variant_id)
            .values_list("rack_id", flat=True)
        )
        return list(
            Rack.objects.using(alias)
            .filter(id__in=rack_ids, branch_id=obj.branch_id)
            .order_by("rack_code")
        )

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


class TenantProductSerializer(ProductSerializer):
    """Native tenant-schema Product create/edit; no shared/default catalog writes.

    Never resolve branch-owned foreign keys using the Django default manager.
    """

    def _scope(self):
        request = self.context.get("request")
        if not request:
            raise serializers.ValidationError({"branch": "Branch context is required."})
        raw = (
            request.data.get("branch")
            if request.method in {"POST", "PUT", "PATCH"}
            else None
        )
        raw = (
            raw
            or request.query_params.get("branch")
            or request.headers.get("X-Branch-ID")
        )
        try:
            branch = Branch.objects.using("default").get(pk=int(raw), is_active=True)
        except (TypeError, ValueError, Branch.DoesNotExist):
            raise serializers.ValidationError(
                {"branch": "Select a valid physical branch."}
            )
        if branch.branch_code == "CONSOLIDATED" and branch.branch_type == "PHYSICAL":
            return branch, "default"
        if branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise serializers.ValidationError(
                {"branch": "Choose a valid physical branch."}
            )
        from apps.branch_data.schema_routing import register_branch_connection

        return branch, register_branch_connection(branch.pk, branch.tax_mode)

    def get_fields(self):
        fields = super().get_fields()
        branch, alias = self._scope()
        fields["brand"].queryset = Brand.objects.using(alias).filter(is_active=True)
        fields["category"].queryset = Category.objects.using(alias).filter(
            is_active=True
        )
        fields["rack"].queryset = Rack.objects.using(alias).filter(
            branch_id=branch.pk, is_active=True
        )
        fields["branch"].queryset = Branch.objects.using(alias).filter(pk=branch.pk)
        fields["variants"].child.fields["racks"].child_relation.queryset = (
            Rack.objects.using(alias).filter(branch_id=branch.pk, is_active=True)
        )
        return fields

    def validate(self, attrs):
        branch, alias = self._scope()
        selected = attrs.get("branch")
        if selected and selected.pk != branch.pk:
            raise serializers.ValidationError(
                {"branch": "Product branch must match the selected branch."}
            )
        attrs["branch"] = Branch.objects.using(alias).get(pk=branch.pk)
        if self.instance and self.instance.branch_id != branch.pk:
            raise serializers.ValidationError(
                {"branch": "Moving a product between branches is not supported."}
            )
        sku = str(attrs.get("sku", getattr(self.instance, "sku", "")) or "").strip()
        if not sku:
            raise serializers.ValidationError({"sku": "SKU is required."})
        q = Product.objects.using(alias).filter(sku__iexact=sku, is_deleted=False)
        if self.instance:
            q = q.exclude(pk=self.instance.pk)
        if q.exists():
            raise serializers.ValidationError(
                {"sku": "SKU already exists in this branch."}
            )
        attrs["sku"] = sku
        supplier_id = attrs.get("supplier")
        if supplier_id not in (None, "", 0, "0"):
            from apps.suppliers.models import Supplier

            if (
                not Supplier.objects.using(alias)
                .filter(pk=supplier_id, branch_id=branch.pk, is_deleted=False)
                .exists()
            ):
                raise serializers.ValidationError(
                    {"supplier": "Select a supplier from the selected branch."}
                )
        tax = attrs.get("tax_treatment", getattr(self.instance, "tax_treatment", "VAT"))
        attrs["vat_rate"] = 5 if tax == "VAT" else 0
        if tax != "VAT":
            attrs["vat_inclusive"] = False
        attrs["compatible_models"] = attrs.get("compatible_models") or "All Models"
        return attrs

    def _physical_supplier_id(self, obj):
        return obj.supplier_id

    def to_representation(self, instance):
        data = serializers.ModelSerializer.to_representation(self, instance)
        data["supplier"] = instance.supplier_id
        return data

    def get_branch_name(self, obj):
        return (
            Branch.objects.using("default")
            .filter(pk=obj.branch_id)
            .values_list("branch_name", flat=True)
            .first()
        )

    def get_branch_code(self, obj):
        return (
            Branch.objects.using("default")
            .filter(pk=obj.branch_id)
            .values_list("branch_code", flat=True)
            .first()
        )

    def get_supplier_name(self, obj):
        if not obj.supplier_id:
            return None
        from apps.suppliers.models import Supplier

        return (
            Supplier.objects.using(obj._state.db)
            .filter(pk=obj.supplier_id)
            .values_list("supplier_name", flat=True)
            .first()
        )

    def get_rack_code(self, obj):
        codes = list(
            Rack.objects.using(obj._state.db)
            .filter(product_variants__product_id=obj.pk)
            .distinct()
            .values_list("rack_code", flat=True)
        )
        return (
            ", ".join(codes) if codes else (obj.rack.rack_code if obj.rack_id else None)
        )

    def get_total_available_qty(self, obj):
        stocks = ProductStock.objects.using(obj._state.db).filter(
            product_id=obj.pk, branch_id=obj.branch_id
        )
        return sum(
            max(0, int(item.current_stock) - int(item.reserved_stock))
            for item in stocks
        )

    def _save_variants(self, obj, supplied, *, initial=False):
        alias = obj._state.db
        desired_ids = []
        if not obj.has_variants:
            supplied = supplied[:1] if supplied else [{}]
        for row in supplied:
            row = dict(row)
            racks = row.pop("racks", [])
            qty = row.pop("initial_stock", None)
            variant_id = row.pop("id", None)
            row.pop("available_qty", None)
            row.pop("is_base", None)
            row["attributes"] = row.get("attributes", {}) if obj.has_variants else {}
            row["is_base"] = not obj.has_variants
            if not obj.has_variants:
                existing = (
                    ProductVariant.objects.using(alias)
                    .filter(product_id=obj.pk, is_base=True)
                    .first()
                )
            else:
                existing = (
                    ProductVariant.objects.using(alias)
                    .filter(product_id=obj.pk, pk=variant_id, is_base=False)
                    .first()
                    if variant_id
                    else None
                )
            if existing:
                for key, val in row.items():
                    setattr(existing, key, val)
                existing.save(using=alias)
                variant = existing
            else:
                variant = ProductVariant.objects.using(alias).create(
                    product_id=obj.pk, **row
                )
            # Explicitly write the M2M through rows into the same tenant schema.
            # The relationship manager can otherwise route to a legacy alias
            # (vat/public or non_vat/public), causing FK failures on COMMIT.
            through = ProductVariant.racks.through
            desired_rack_ids = {rack.pk for rack in racks}
            linked = set(
                through.objects.using(alias)
                .filter(productvariant_id=variant.pk)
                .values_list("rack_id", flat=True)
            )
            removed = linked - desired_rack_ids
            added = desired_rack_ids - linked
            if removed:
                through.objects.using(alias).filter(
                    productvariant_id=variant.pk, rack_id__in=removed
                ).delete()
            if added:
                through.objects.using(alias).bulk_create(
                    [
                        through(productvariant_id=variant.pk, rack_id=rack_id)
                        for rack_id in sorted(added)
                    ]
                )
            desired_ids.append(variant.pk)
            stock_variant_id = variant.pk if obj.has_variants else None
            stock, _ = ProductStock.objects.using(alias).get_or_create(
                product_id=obj.pk,
                branch_id=obj.branch_id,
                variant_id=stock_variant_id,
                warehouse="",
                defaults={"current_stock": 0, "reorder_level": obj.reorder_level},
            )
            # Opening stock is a one-time receipt only on product creation.
            # Both the stock balance and its audit movement use the tenant alias.
            if qty not in (None, "", 0, "0"):
                if not initial:
                    raise serializers.ValidationError(
                        {
                            "variants": "Use Stock Adjustments or GRN to change existing stock."
                        }
                    )
                self._create_opening_stock(obj, variant, stock, int(qty))
        if not initial:
            omitted = (
                ProductVariant.objects.using(alias)
                .filter(product_id=obj.pk)
                .exclude(pk__in=desired_ids)
            )
            if omitted.exists():
                raise serializers.ValidationError(
                    {
                        "variants": "Deleting existing variants requires a separate stock-safe workflow."
                    }
                )

    def _create_opening_stock(self, product, variant, stock, qty):
        """Record opening stock and its valuation atomically in one tenant DB."""
        from decimal import Decimal
        from django.utils import timezone
        from apps.common.tax import (
            calculate_inventory_tax,
            quantize_money,
            quantize_unit,
        )
        from .services import generate_stock_number

        alias = product._state.db
        if alias != stock._state.db or alias != variant._state.db:
            raise serializers.ValidationError(
                {"variants": "Opening stock must use the product's tenant database."}
            )
        if qty <= 0 or stock.current_stock or stock.reserved_stock:
            raise serializers.ValidationError(
                {"variants": "Opening quantity must be positive and stock must be new."}
            )
        cost = variant.purchase_price
        if cost is None or Decimal(str(cost)) <= 0:
            raise serializers.ValidationError(
                {
                    "variants": "Enter a purchase price greater than zero for opening stock valuation."
                }
            )
        treatment = product.tax_treatment
        rate = product.vat_rate if treatment == "VAT" else 0
        valuation = calculate_inventory_tax(
            unit_cost=Decimal(str(cost)),
            vat_percentage=rate,
            tax_treatment={
                "VAT": "STANDARD_VAT",
                "ZERO_VAT": "ZERO_RATED",
                "NON_VAT": "OUT_OF_SCOPE",
            }.get(treatment, "OUT_OF_SCOPE"),
            vat_inclusive=bool(product.vat_inclusive) if treatment == "VAT" else False,
            recoverable=treatment == "VAT",
        )
        carrying = quantize_unit(valuation["capitalized_unit_cost"])
        stock.current_stock = qty
        stock.reorder_level = product.reorder_level
        stock.average_unit_cost = carrying
        stock.average_unit_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.recoverable_vat_per_unit = valuation["recoverable_vat_per_unit"]
        stock.capitalized_vat_per_unit = valuation["capitalized_vat_per_unit"]
        stock.last_purchase_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.last_purchase_cost = quantize_unit(
            valuation["unit_cost_excluding_vat"] + valuation["vat_per_unit"]
        )
        stock.last_tax_treatment = treatment
        stock.last_vat_percentage = rate
        stock.last_stock_update = timezone.now()
        stock.valuation_updated_at = timezone.now()
        stock.save(using=alias)

        # The non-variant base record has a null stock.variant FK by design.
        ledger_variant_id = variant.pk if product.has_variants else None
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        actor_id = (
            getattr(actor, "pk", None)
            if getattr(actor, "is_authenticated", False)
            else None
        )
        for _ in range(5):
            number = generate_stock_number()
            if (
                not StockMovement.objects.using(alias)
                .filter(movement_number=number)
                .exists()
            ):
                break
        StockMovement.objects.using(alias).create(
            movement_number=number,
            product_id=product.pk,
            variant_id=ledger_variant_id,
            branch_id=product.branch_id,
            movement_type="OPENING",
            quantity=qty,
            previous_stock=0,
            new_stock=qty,
            quantity_before=0,
            quantity_after=qty,
            warehouse="",
            reference_type="PRODUCT_CREATE",
            reference_id=str(product.pk),
            remarks=f"Opening stock from product creation"
            + (f" [Shared actor user ID: {actor_id}]" if actor_id else ""),
            unit_cost_excluding_vat=valuation["unit_cost_excluding_vat"],
            vat_treatment=treatment,
            vat_percentage=rate,
            recoverable_vat_amount=quantize_money(
                Decimal(qty) * valuation["recoverable_vat_per_unit"]
            ),
            non_recoverable_vat_amount=quantize_money(
                Decimal(qty) * valuation["capitalized_vat_per_unit"]
            ),
            capitalized_unit_cost=carrying,
            net_value_change=quantize_money(Decimal(qty) * carrying),
            gross_value_change=quantize_money(
                Decimal(qty)
                * (valuation["unit_cost_excluding_vat"] + valuation["vat_per_unit"])
            ),
            running_stock_value=quantize_money(Decimal(qty) * carrying),
            source_document_type="PRODUCT_CREATE",
            source_document_number=str(product.pk),
            is_vat_relevant=treatment in {"VAT", "ZERO_VAT"},
        )

    def create(self, validated_data):
        branch, alias = self._scope()
        rows = validated_data.pop("variants", [])
        supplier_id = validated_data.pop("supplier", None)
        if supplier_id:
            validated_data["supplier_id"] = supplier_id
        if not validated_data.get("barcode"):
            validated_data["barcode"] = "GHZ" + secrets.token_hex(6).upper()
        validated_data["branch_id"] = branch.pk
        validated_data.pop("branch", None)
        with transaction.atomic(using=alias):
            obj = Product.objects.using(alias).create(**validated_data)
            self._save_variants(obj, rows, initial=True)
        return obj

    def update(self, instance, validated_data):
        branch, alias = self._scope()
        rows = validated_data.pop("variants", None)
        supplier_id = validated_data.pop("supplier", serializers.empty)
        if supplier_id is not serializers.empty:
            validated_data["supplier_id"] = supplier_id
        validated_data.pop("branch", None)
        with transaction.atomic(using=alias):
            for key, val in validated_data.items():
                setattr(instance, key, val)
            instance.save(using=alias)
            if rows is not None:
                self._save_variants(instance, rows)
        return instance
