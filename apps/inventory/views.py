from collections import defaultdict

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.viewsets import (
    ModelViewSet,
    ReadOnlyModelViewSet,
)

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
    variant_label,
)
from .services import adjust_stock


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
    search_fields = [
        "rack_code",
        "rack_name",
        "branch__branch_name",
        "branch__branch_code",
    ]
    filterset_fields = ["branch", "is_active"]


class ProductViewSet(ModelViewSet):
    queryset = (
        Product.objects.filter(is_deleted=False)
        .select_related(
            "brand",
            "category",
            "supplier",
            "branch",
            "rack",
        )
        .prefetch_related(
            "variants",
            "stocks",
        )
    )
    serializer_class = ProductSerializer
    search_fields = [
        "product_name",
        "sku",
        "barcode",
        "compatible_models",
    ]
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
    queryset = ProductStock.objects.select_related(
        "product",
        "product__brand",
        "product__category",
        "variant",
        "branch",
    ).filter(Q(product__has_variants=False) | Q(variant__isnull=False))
    serializer_class = ProductStockSerializer
    filterset_fields = [
        "branch",
        "product",
        "variant",
    ]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        branch_id = request.query_params.get("branch")
        product_id = request.query_params.get("product")
        search = request.query_params.get(
            "search",
            "",
        ).strip()
        status_filter = (
            request.query_params.get(
                "status",
                "",
            )
            .strip()
            .lower()
        )

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        if search:
            queryset = queryset.filter(
                Q(product__product_name__icontains=search)
                | Q(product__sku__icontains=search)
                | Q(branch__branch_name__icontains=search)
                | Q(branch__branch_code__icontains=search)
            )

        groups = {}

        for stock in queryset:
            key = (
                stock.product_id,
                stock.variant_id,
            )

            if key not in groups:
                groups[key] = {
                    "product_id": stock.product_id,
                    "product_name": stock.product.product_name,
                    "sku": stock.product.sku,
                    "brand_name": stock.product.brand.name,
                    "category_name": stock.product.category.name,
                    "variant_id": stock.variant_id,
                    "variant_label": variant_label(stock.variant),
                    "reorder_level": stock.reorder_level,
                    "branch_stocks": [],
                    "total_current": 0,
                    "total_reserved": 0,
                    "total_damaged": 0,
                    "total_available": 0,
                }

            available = stock.available_stock
            group = groups[key]

            group["branch_stocks"].append(
                {
                    "branch_id": stock.branch_id,
                    "branch_code": stock.branch.branch_code,
                    "branch_name": stock.branch.branch_name,
                    "current_stock": stock.current_stock,
                    "reserved_stock": stock.reserved_stock,
                    "damaged_stock": stock.damaged_stock,
                    "available_stock": available,
                }
            )

            group["total_current"] += stock.current_stock
            group["total_reserved"] += stock.reserved_stock
            group["total_damaged"] += stock.damaged_stock
            group["total_available"] += available
            group["reorder_level"] = max(
                group["reorder_level"],
                stock.reorder_level,
            )

        results = []

        for group in groups.values():
            if group["total_available"] <= 0:
                status = "out"
            elif group["total_available"] < 10:
                status = "low"
            else:
                status = "ok"

            group["status"] = status
            group["branch_stocks"].sort(key=lambda item: (item["branch_code"] or ""))

            if status_filter and status_filter != status:
                continue

            results.append(group)

        results.sort(
            key=lambda item: (
                item["product_name"].lower(),
                item["variant_label"].lower(),
            )
        )

        return ok(
            {
                "count": len(results),
                "results": results,
            },
            message=("Stock overview fetched " "successfully."),
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="low-stock",
    )
    def low_stock(self, request):
        queryset = self.get_queryset()
        items = [stock for stock in queryset if stock.available_stock < 10]

        return ok(
            ProductStockSerializer(
                items,
                many=True,
            ).data
        )


class StockMovementViewSet(ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related(
        "product",
        "variant",
        "branch",
        "performed_by",
    ).all()
    serializer_class = StockMovementSerializer
    filterset_fields = [
        "branch",
        "product",
        "variant",
        "movement_type",
    ]
    search_fields = [
        "movement_number",
        "reference_id",
        "product__product_name",
        "product__sku",
        "branch__branch_code",
        "branch__branch_name",
    ]
    ordering_fields = [
        "created_at",
        "quantity",
    ]
    ordering = ["-created_at"]


class StockAdjustmentViewSet(ModelViewSet):
    queryset = StockAdjustment.objects.select_related(
        "product",
        "variant",
        "branch",
        "approved_by",
        "created_by",
    ).all()
    serializer_class = StockAdjustmentSerializer
    filterset_fields = [
        "branch",
        "status",
        "product",
        "variant",
        "adjustment_type",
    ]
    search_fields = [
        "adjustment_number",
        "product__product_name",
        "product__sku",
        "reason",
    ]

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        branch = serializer.validated_data.get("branch") or getattr(
            user, "branch", None
        )

        if not branch:
            from rest_framework.exceptions import (
                ValidationError,
            )

            raise ValidationError(
                {"branch": ("Branch is required for " "a stock adjustment.")}
            )

        adjustment_type = serializer.validated_data["adjustment_type"]
        quantity = serializer.validated_data["quantity"]

        signed_quantity = -quantity if adjustment_type == "DEDUCT" else quantity

        adjustment_number = "SA-" f"{timezone.now():%Y%m%d%H%M%S%f}"

        adjustment = serializer.save(
            adjustment_number=adjustment_number,
            branch=branch,
            status="APPROVED",
            approved_by=user,
            created_by=user,
            updated_by=user,
        )

        adjust_stock(
            product=adjustment.product,
            variant=adjustment.variant,
            branch=branch,
            quantity=signed_quantity,
            movement_type="ADJUSTMENT",
            performed_by=user,
            reference_type="STOCK_ADJUSTMENT",
            reference_id=adjustment.id,
            remarks=(f"{adjustment.reason}. " f"{adjustment.remarks}").strip(),
        )


@api_view(["GET"])
def low_stock_products(request):
    queryset = ProductStock.objects.select_related(
        "product",
        "variant",
        "branch",
        "product__brand",
        "product__category",
    ).filter(Q(product__has_variants=False) | Q(variant__isnull=False))

    branch_id = request.query_params.get("branch")

    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)

    items = [stock for stock in queryset if stock.available_stock < 10]

    return ok(
        ProductStockSerializer(
            items,
            many=True,
        ).data,
        message=("Low stock products fetched " "successfully."),
    )
