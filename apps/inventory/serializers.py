import json

from django.db import transaction
from rest_framework import serializers

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    ProductVariant,
    StockAdjustment,
    StockMovement,
)


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class ProductVariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    available_qty = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, default=0
    )
    sku = serializers.CharField(max_length=100, validators=[])
    barcode = serializers.CharField(
        max_length=120, required=False, allow_blank=True, allow_null=True, validators=[]
    )
    effective_purchase_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    effective_retail_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    effective_wholesale_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    effective_minimum_selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "product",
            "variant_name",
            "sku",
            "barcode",
            "attributes",
            "available_qty",
            "purchase_price",
            "retail_price",
            "wholesale_price",
            "minimum_selling_price",
            "effective_purchase_price",
            "effective_retail_price",
            "effective_wholesale_price",
            "effective_minimum_selling_price",
            "is_default",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["product", "created_at", "updated_at"]

    def validate_available_qty(self, value):
        return 0 if value in (None, "") else value

    def validate_attributes(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Variant attributes must be supplied as key-value pairs."
            )

        cleaned = {}
        for key, item_value in value.items():
            clean_key = str(key).strip()
            clean_value = str(item_value).strip()
            if not clean_key or not clean_value:
                continue
            cleaned[clean_key] = clean_value

        return cleaned


class ProductSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True, allow_null=True
    )
    product_image_url = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, required=False)
    variant_count = serializers.SerializerMethodField()
    total_available_qty = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "is_deleted"]

    def get_product_image_url(self, obj):
        if not obj.product_image:
            return None
        request = self.context.get("request")
        url = obj.product_image.url
        return request.build_absolute_uri(url) if request else url

    def get_variant_count(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get("variants")
        if prefetched is not None:
            return len([variant for variant in prefetched if variant.is_active])
        return obj.variants.filter(is_active=True).count()

    def get_total_available_qty(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get("variants")
        if prefetched is not None:
            return sum(
                int(variant.available_qty or 0)
                for variant in prefetched
                if variant.is_active
            )

        return sum(
            int(quantity or 0)
            for quantity in obj.variants.filter(is_active=True).values_list(
                "available_qty",
                flat=True,
            )
        )

    def to_internal_value(self, data):
        """Convert multipart QueryDict input into a normal dictionary.

        DRF treats QueryDict as HTML-form input. For a nested ``many=True``
        serializer it then looks for keys such as ``variants[0].sku`` and can
        ignore a JSON string stored under the single ``variants`` key. The
        product form intentionally sends that nested list as JSON, so convert
        the request data to a plain dict before normal serializer processing.
        """
        if hasattr(data, "getlist"):
            mutable = {key: data.get(key) for key in data.keys()}
        else:
            mutable = dict(data)

        variants = mutable.get("variants", serializers.empty)

        if variants is not serializers.empty:
            if variants in (None, ""):
                mutable["variants"] = []
            elif isinstance(variants, str):
                try:
                    parsed_variants = json.loads(variants)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise serializers.ValidationError(
                        {"variants": "The submitted variant data is invalid."}
                    ) from exc

                if not isinstance(parsed_variants, list):
                    raise serializers.ValidationError(
                        {"variants": "Variants must be submitted as a list."}
                    )

                mutable["variants"] = parsed_variants

        return super().to_internal_value(mutable)

    def validate_variants(self, variants):
        skus = set()
        barcodes = set()
        default_count = 0

        for index, variant in enumerate(variants):
            sku = str(variant.get("sku", "")).strip()
            barcode = str(variant.get("barcode") or "").strip()

            if not sku:
                raise serializers.ValidationError(
                    {index: {"sku": "Variant SKU is required."}}
                )

            normalized_sku = sku.lower()
            if normalized_sku in skus:
                raise serializers.ValidationError(
                    {index: {"sku": "Each variant must have a unique SKU."}}
                )
            skus.add(normalized_sku)

            if barcode:
                normalized_barcode = barcode.lower()
                if normalized_barcode in barcodes:
                    raise serializers.ValidationError(
                        {index: {"barcode": "Each variant must have a unique barcode."}}
                    )
                barcodes.add(normalized_barcode)

            if variant.get("is_default"):
                default_count += 1

        if default_count > 1:
            raise serializers.ValidationError(
                "Only one variant can be selected as the default variant."
            )

        supplied_ids = [variant.get("id") for variant in variants if variant.get("id")]
        sku_conflicts = ProductVariant.objects.filter(
            sku__in=[variant["sku"] for variant in variants]
        )
        barcode_values = [
            variant.get("barcode") for variant in variants if variant.get("barcode")
        ]
        barcode_conflicts = ProductVariant.objects.filter(barcode__in=barcode_values)

        if supplied_ids:
            sku_conflicts = sku_conflicts.exclude(id__in=supplied_ids)
            barcode_conflicts = barcode_conflicts.exclude(id__in=supplied_ids)

        if sku_conflicts.exists():
            raise serializers.ValidationError(
                "One or more variant SKUs are already used by another product variant."
            )
        if barcode_conflicts.exists():
            raise serializers.ValidationError(
                "One or more variant barcodes are already used by another product variant."
            )

        return variants

    @staticmethod
    def _sync_variants(product, variants_data):
        existing = {variant.id: variant for variant in product.variants.all()}
        retained_ids = []

        for variant_data in variants_data:
            variant_id = variant_data.pop("id", None)
            variant_data["barcode"] = variant_data.get("barcode") or None
            variant_data["available_qty"] = variant_data.get("available_qty") or 0

            if variant_id and variant_id in existing:
                variant = existing[variant_id]
                for field, value in variant_data.items():
                    setattr(variant, field, value)
                variant.save()
            else:
                variant = ProductVariant.objects.create(
                    product=product,
                    **variant_data,
                )

            retained_ids.append(variant.id)

        product.variants.exclude(id__in=retained_ids).delete()

        # When variants exist and none was selected, make the first one default.
        variants = list(product.variants.order_by("id"))
        if variants and not any(variant.is_default for variant in variants):
            first = variants[0]
            first.is_default = True
            first.save(update_fields=["is_default", "updated_at"])

    @transaction.atomic
    def create(self, validated_data):
        variants_data = validated_data.pop("variants", [])
        product = super().create(validated_data)
        self._sync_variants(product, variants_data)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        variants_supplied = "variants" in validated_data
        variants_data = validated_data.pop("variants", [])
        product = super().update(instance, validated_data)
        if variants_supplied:
            self._sync_variants(product, variants_data)
        return product


class ProductStockSerializer(serializers.ModelSerializer):
    available_stock = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.product_name", read_only=True)

    class Meta:
        model = ProductStock
        fields = "__all__"


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = "__all__"


class StockAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockAdjustment
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "created_by", "updated_by"]
