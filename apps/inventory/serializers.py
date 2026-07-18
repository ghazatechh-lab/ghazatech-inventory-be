from rest_framework import serializers

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    StockMovement,
    StockAdjustment,
)


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    product_image_url = serializers.SerializerMethodField(read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = [
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "deleted_by",
        ]
        extra_kwargs = {
            "product_image": {
                "required": False,
                "allow_null": True,
            }
        }

    def to_internal_value(self, data):
        """Ignore an empty/string image value during partial product updates.

        The frontend should only send ``product_image`` when a new file is
        selected. This guard also prevents old image URLs from being validated
        as uploaded files.
        """
        mutable_data = data.copy() if hasattr(data, "copy") else dict(data)
        image = mutable_data.get("product_image")

        if image in (None, "", "null", "undefined") or isinstance(image, str):
            mutable_data.pop("product_image", None)

        return super().to_internal_value(mutable_data)

    def get_product_image_url(self, obj):
        if not obj.product_image:
            return None

        request = self.context.get("request")
        image_url = obj.product_image.url
        return request.build_absolute_uri(image_url) if request else image_url

    def validate_product_image(self, image):
        if not image:
            return image

        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        content_type = getattr(image, "content_type", "")

        if content_type not in allowed_types:
            raise serializers.ValidationError(
                "Only JPG, PNG, and WebP product images are allowed."
            )

        max_size = 5 * 1024 * 1024
        if image.size > max_size:
            raise serializers.ValidationError(
                "Product image size must not exceed 5 MB."
            )

        return image


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
