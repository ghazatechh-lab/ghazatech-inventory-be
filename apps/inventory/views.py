from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from rest_framework.decorators import api_view

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    StockMovement,
    StockAdjustment,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductSerializer,
    ProductStockSerializer,
    StockMovementSerializer,
    StockAdjustmentSerializer,
)
from apps.common.response import ok


class BrandViewSet(ModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    search_fields = ["name"]


class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]


class ProductViewSet(ModelViewSet):
    queryset = Product.objects.filter(is_deleted=False).select_related(
        "brand", "category", "supplier"
    )
    serializer_class = ProductSerializer
    search_fields = ["product_name", "sku", "barcode", "compatible_models"]
    filterset_fields = ["brand", "category", "is_active"]

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save()


class StockViewSet(ReadOnlyModelViewSet):
    queryset = ProductStock.objects.select_related("product", "branch")
    serializer_class = ProductStockSerializer
    filterset_fields = ["branch", "product"]

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        data = [
            x
            for x in self.filter_queryset(self.get_queryset())
            if x.available_stock <= x.reorder_level
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

    serializer = ProductStockSerializer(low_stock_items, many=True)

    return ok(serializer.data, message="Low stock products fetched successfully")
