import json

from django.db import transaction
from rest_framework import serializers

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
    available_qty = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, default=0
    )
    purchase_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "attributes",
            "available_qty",
            "purchase_price",
            "retail_price",
            "wholesale_price",
            "minimum_selling_price",
            "is_base",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_base", "created_at", "updated_at"]

    def validate_available_qty(self, value):
        return 0 if value in (None, "") else value

    def validate_attributes(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Attributes must be key-value pairs.")
        return {
            str(key).strip(): str(item_value).strip()
            for key, item_value in value.items()
            if str(key).strip() and str(item_value).strip()
        }


class ProductSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    rack_code = serializers.CharField(
        source="rack.rack_code", read_only=True, allow_null=True
    )
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True, allow_null=True
    )
    product_image_url = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, required=False)
    total_available_qty = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "is_deleted"]

    def get_product_image_url(self, obj):
        if not obj.product_image:
            return None
        request = self.context.get("request")
        return (
            request.build_absolute_uri(obj.product_image.url)
            if request
            else obj.product_image.url
        )

    def get_total_available_qty(self, obj):
        return sum(
            obj.variants.filter(is_active=True).values_list("available_qty", flat=True)
        )

    def to_internal_value(self, data):
        mutable = (
            {key: data.get(key) for key in data.keys()}
            if hasattr(data, "getlist")
            else dict(data)
        )
        variants = mutable.get("variants", serializers.empty)
        if variants is not serializers.empty:
            if variants in (None, ""):
                mutable["variants"] = []
            elif isinstance(variants, str):
                try:
                    mutable["variants"] = json.loads(variants)
                except json.JSONDecodeError as exc:
                    raise serializers.ValidationError(
                        {"variants": "Invalid variant data."}
                    ) from exc
        return super().to_internal_value(mutable)

    def validate(self, attrs):
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        rack = attrs.get("rack", getattr(self.instance, "rack", None))
        if rack and branch and rack.branch_id != branch.id:
            raise serializers.ValidationError(
                {"rack": "Selected rack does not belong to the selected branch."}
            )
        return attrs

    def validate_variants(self, variants):
        has_variants = self.initial_data.get("has_variants")
        has_variants = str(has_variants).lower() in {"true", "1", "yes"}
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
    def _sync_variants(product, variants_data):
        existing = {variant.id: variant for variant in product.variants.all()}
        retained_ids = []

        if not product.has_variants:
            base_data = variants_data[0] if variants_data else {}
            base = product.variants.filter(is_base=True).first()
            if not base:
                base = ProductVariant(product=product, is_base=True)
            base.attributes = {}
            base.available_qty = base_data.get("available_qty") or 0
            base.purchase_price = base_data.get("purchase_price") or None
            base.retail_price = base_data.get("retail_price") or 0
            base.wholesale_price = base_data.get("wholesale_price") or 0
            base.minimum_selling_price = base_data.get("minimum_selling_price") or 0
            base.is_active = True
            base.save()
            product.variants.exclude(id=base.id).delete()
            return

        product.variants.filter(is_base=True).delete()
        for variant_data in variants_data:
            variant_id = variant_data.pop("id", None)
            variant_data["is_base"] = False
            variant_data["available_qty"] = variant_data.get("available_qty") or 0
            variant_data["purchase_price"] = variant_data.get("purchase_price") or None
            if variant_id and variant_id in existing:
                variant = existing[variant_id]
                for field, value in variant_data.items():
                    setattr(variant, field, value)
                variant.save()
            else:
                variant = ProductVariant.objects.create(product=product, **variant_data)
            retained_ids.append(variant.id)
        product.variants.exclude(id__in=retained_ids).delete()

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
        if variants_supplied or not product.has_variants:
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
