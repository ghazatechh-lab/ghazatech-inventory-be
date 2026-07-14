from rest_framework import serializers
from .models import *


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "is_deleted"]


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
