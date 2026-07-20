from rest_framework.decorators import action, api_view
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    ProductVariant,
    StockAdjustment,
    StockMovement,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductSerializer,
    ProductStockSerializer,
    ProductVariantSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
)
from apps.common.response import ok


class BrandViewSet(ModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class ProductViewSet(ModelViewSet):
    queryset = (
        Product.objects.filter(is_deleted=False)
        .select_related("brand", "category", "supplier")
        .prefetch_related("variants", "stocks")
    )
    serializer_class = ProductSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = [
        "product_name",
        "sku",
        "barcode",
        "compatible_models",
        "variants__variant_name",
        "variants__sku",
        "variants__barcode",
    ]
    filterset_fields = ["brand", "category", "is_active"]

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save(update_fields=["is_deleted", "deleted_by", "updated_at"])


class ProductVariantViewSet(ModelViewSet):
    queryset = ProductVariant.objects.select_related(
        "product", "product__brand", "product__category"
    )
    serializer_class = ProductVariantSerializer
    filterset_fields = ["product", "is_active", "is_default"]
    search_fields = ["variant_name", "sku", "barcode"]

    def perform_create(self, serializer):
        product_id = self.request.data.get("product")
        product = Product.objects.get(pk=product_id, is_deleted=False)
        serializer.save(product=product)


class StockViewSet(ReadOnlyModelViewSet):
    queryset = ProductStock.objects.select_related("product", "branch")
    serializer_class = ProductStockSerializer
    filterset_fields = ["branch", "product"]

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        data = [
            item
            for item in self.filter_queryset(self.get_queryset())
            if item.available_stock <= item.reorder_level
        ]
        return ok(ProductStockSerializer(data, many=True).data)


class StockMovementViewSet(ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related("product", "branch")
    serializer_class = StockMovementSerializer
    filterset_fields = ["branch", "product", "movement_type"]
    search_fields = ["movement_number", "reference_id"]


class StockAdjustmentViewSet(ModelViewSet):
    queryset = StockAdjustment.objects.all()
    serializer_class = StockAdjustmentSerializer
    filterset_fields = ["branch", "status", "product"]

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
            branch=serializer.validated_data.get("branch") or self.request.user.branch,
        )


@api_view(["GET"])
def low_stock_products(request):
    queryset = ProductStock.objects.select_related(
        "product",
        "branch",
        "product__brand",
        "product__category",
    )

    branch_id = request.query_params.get("branch")
    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)

    low_stock_items = [
        stock for stock in queryset if stock.available_stock <= stock.reorder_level
    ]

    return ok(
        ProductStockSerializer(low_stock_items, many=True).data,
        message="Low stock products fetched successfully",
    )
