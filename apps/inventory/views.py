from rest_framework.decorators import action, api_view
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.common.response import ok
from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    Rack,
    StockAdjustment,
    StockMovement,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductSerializer,
    ProductStockSerializer,
    RackSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
)


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


class RackViewSet(ModelViewSet):
    queryset = Rack.objects.select_related("branch").all()
    serializer_class = RackSerializer
    search_fields = ["rack_code", "rack_name", "branch__branch_name"]
    filterset_fields = ["branch", "is_active"]


class ProductViewSet(ModelViewSet):
    queryset = (
        Product.objects.filter(is_deleted=False)
        .select_related("brand", "category", "supplier", "branch", "rack")
        .prefetch_related("variants")
    )
    serializer_class = ProductSerializer
    search_fields = ["product_name", "sku", "barcode", "compatible_models"]
    filterset_fields = [
        "brand",
        "category",
        "branch",
        "rack",
        "has_variants",
        "is_active",
    ]

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
        "product", "branch", "product__brand", "product__category"
    )
    branch_id = request.query_params.get("branch")
    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)
    items = [
        stock for stock in queryset if stock.available_stock <= stock.reorder_level
    ]
    return ok(
        ProductStockSerializer(items, many=True).data,
        message="Low stock products fetched successfully",
    )
