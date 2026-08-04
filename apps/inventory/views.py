from decimal import Decimal

from collections import defaultdict

from django.db import transaction
from django.db.models import ExpressionWrapper, F, IntegerField, Q, Sum
from django.utils import timezone
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import (
    ModelViewSet,
    ReadOnlyModelViewSet,
)

from apps.common.response import ok

from .models import (
    Brand,
    Category,
    Product,
    ProductVariant,
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
from .permissions import ReferenceDataPermission
from rest_framework import status


class BrandViewSet(ModelViewSet):
    permission_classes = [ReferenceDataPermission]
    ordering_fields = ["name", "is_active", "created_at"]
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class CategoryViewSet(ModelViewSet):
    permission_classes = [ReferenceDataPermission]
    ordering_fields = ["name", "is_active", "created_at"]
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class RackViewSet(ModelViewSet):
    permission_classes = [ReferenceDataPermission]
    ordering_fields = [
        "rack_code",
        "rack_name",
        "branch__branch_code",
        "is_active",
        "created_at",
    ]
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
    ordering_fields = ["product_name", "sku", "condition", "created_at"]
    filterset_fields = [
        "brand",
        "category",
        "rack",
        "has_variants",
        "is_active",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_id = self.request.query_params.get("branch")

        if branch_id:
            queryset = queryset.filter(
                Q(branch_id=branch_id)
                | Q(stocks__branch_id=branch_id, stocks__current_stock__gt=0)
            ).distinct()

        return queryset

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save()


class StockViewSet(ReadOnlyModelViewSet):
    serializer_class = ProductStockSerializer
    filterset_fields = [
        "branch",
        "product",
        "variant",
    ]

    def get_queryset(self):
        """
        Return stock rows with database-calculated classified totals.

        The *_db aliases can be used by serializers, filtering, ordering,
        reports, and values() queries. The model properties remain available
        for code working with individual ProductStock objects.
        """
        return (
            ProductStock.objects.select_related(
                "product",
                "product__brand",
                "product__category",
                "variant",
                "branch",
            )
            .prefetch_related("product__variants")
            .filter(Q(product__has_variants=False) | Q(variant__isnull=False))
            .annotate(
                total_quantity_db=ExpressionWrapper(
                    F("regular_quantity") + F("restricted_quantity"),
                    output_field=IntegerField(),
                ),
                available_regular_db=ExpressionWrapper(
                    F("regular_quantity") - F("reserved_regular_quantity"),
                    output_field=IntegerField(),
                ),
                available_restricted_db=ExpressionWrapper(
                    F("restricted_quantity") - F("reserved_restricted_quantity"),
                    output_field=IntegerField(),
                ),
                total_available_db=ExpressionWrapper(
                    F("regular_quantity")
                    + F("restricted_quantity")
                    - F("reserved_regular_quantity")
                    - F("reserved_restricted_quantity"),
                    output_field=IntegerField(),
                ),
            )
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        branch_id = request.query_params.get("branch")
        product_id = request.query_params.get("product")
        category_id = request.query_params.get("category")
        search = request.query_params.get(
            "search", request.query_params.get("q", "")
        ).strip()
        status_filter = request.query_params.get("status", "").strip().lower()
        min_price = request.query_params.get("min_price")
        max_price = request.query_params.get("max_price")
        ordering = request.query_params.get("ordering", "product_name")

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        if category_id:
            queryset = queryset.filter(product__category_id=category_id)
        if search:
            queryset = queryset.filter(
                Q(product__product_name__icontains=search)
                | Q(product__sku__icontains=search)
                | Q(branch__branch_name__icontains=search)
                | Q(branch__branch_code__icontains=search)
            )

        groups = {}
        for stock in queryset:
            key = (stock.product_id, stock.variant_id)
            if stock.variant_id:
                retail_price = stock.variant.retail_price
            else:
                base_variant = next(
                    (
                        variant
                        for variant in stock.product.variants.all()
                        if variant.is_base
                    ),
                    None,
                )
                retail_price = base_variant.retail_price if base_variant else 0

            if key not in groups:
                groups[key] = {
                    "product_id": stock.product_id,
                    "product_name": stock.product.product_name,
                    "sku": stock.product.sku,
                    "brand_name": stock.product.brand.name,
                    "category_id": stock.product.category_id,
                    "category_name": stock.product.category.name,
                    "variant_id": stock.variant_id,
                    "variant_label": variant_label(stock.variant),
                    "retail_price": retail_price,
                    "reorder_level": stock.reorder_level,
                    "branch_stocks": [],
                    "total_current": 0,
                    "total_reserved": 0,
                    "total_damaged": 0,
                    "total_available": 0,
                    "total_regular": 0,
                    "total_restricted": 0,
                    "total_reserved_regular": 0,
                    "total_reserved_restricted": 0,
                    "total_available_regular": 0,
                    "total_available_restricted": 0,
                    "inventory_value_excluding_vat": 0,
                    "recoverable_vat_value": 0,
                    "capitalized_vat_value": 0,
                    "total_inventory_value": 0,
                    "regular_stock_value": 0,
                    "restricted_stock_value": 0,
                    "average_unit_cost": 0,
                    "vat_treatment": stock.last_tax_treatment,
                    "vat_percentage": stock.last_vat_percentage,
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
                    "regular_quantity": stock.regular_quantity,
                    "restricted_quantity": stock.restricted_quantity,
                    "reserved_regular_quantity": stock.reserved_regular_quantity,
                    "reserved_restricted_quantity": stock.reserved_restricted_quantity,
                    "total_quantity": getattr(
                        stock,
                        "total_quantity_db",
                        stock.total_quantity,
                    ),
                    "available_regular_quantity": max(
                        0,
                        getattr(
                            stock,
                            "available_regular_db",
                            stock.available_regular_quantity,
                        ),
                    ),
                    "available_restricted_quantity": max(
                        0,
                        getattr(
                            stock,
                            "available_restricted_db",
                            stock.available_restricted_quantity,
                        ),
                    ),
                    "total_available_quantity": max(
                        0,
                        getattr(
                            stock,
                            "total_available_db",
                            stock.total_available_quantity,
                        ),
                    ),
                    "damaged_stock": stock.damaged_stock,
                    "available_stock": available,
                    "average_unit_cost_excluding_vat": stock.average_unit_cost_excluding_vat,
                    "recoverable_vat_per_unit": stock.recoverable_vat_per_unit,
                    "capitalized_vat_per_unit": stock.capitalized_vat_per_unit,
                    "average_unit_cost": stock.average_unit_cost,
                    "inventory_value_excluding_vat": stock.inventory_value_excluding_vat,
                    "recoverable_vat_value": stock.recoverable_vat_value,
                    "capitalized_vat_value": stock.capitalized_vat_value,
                    "total_inventory_value": stock.total_inventory_value,
                    "regular_stock_value": stock.regular_stock_value,
                    "restricted_stock_value": stock.restricted_stock_value,
                    "vat_treatment": stock.last_tax_treatment,
                    "vat_percentage": stock.last_vat_percentage,
                }
            )
            group["total_current"] += stock.current_stock
            group["total_reserved"] += stock.reserved_stock
            group["total_regular"] += stock.regular_quantity
            group["total_restricted"] += stock.restricted_quantity
            group["total_reserved_regular"] += stock.reserved_regular_quantity
            group["total_reserved_restricted"] += stock.reserved_restricted_quantity
            group["total_available_regular"] += max(
                0,
                getattr(
                    stock,
                    "available_regular_db",
                    stock.available_regular_quantity,
                ),
            )
            group["total_available_restricted"] += max(
                0,
                getattr(
                    stock,
                    "available_restricted_db",
                    stock.available_restricted_quantity,
                ),
            )
            group["total_damaged"] += stock.damaged_stock
            group["total_available"] += available
            group["inventory_value_excluding_vat"] += float(
                stock.inventory_value_excluding_vat
            )
            group["recoverable_vat_value"] += float(stock.recoverable_vat_value)
            group["capitalized_vat_value"] += float(stock.capitalized_vat_value)
            group["total_inventory_value"] += float(stock.total_inventory_value)
            group["regular_stock_value"] += float(stock.regular_stock_value)
            group["restricted_stock_value"] += float(stock.restricted_stock_value)
            group["average_unit_cost"] = float(stock.average_unit_cost or 0)
            group["vat_treatment"] = stock.last_tax_treatment
            group["vat_percentage"] = float(stock.last_vat_percentage or 0)
            group["reorder_level"] = max(group["reorder_level"], stock.reorder_level)

        results = []
        for group in groups.values():
            total = group["total_available"]
            group["status"] = "out" if total <= 0 else "low" if total < 10 else "ok"
            group["branch_stocks"].sort(key=lambda item: item["branch_code"] or "")

            if status_filter and status_filter != group["status"]:
                continue
            price = float(group["retail_price"] or 0)
            if min_price not in (None, "") and price < float(min_price):
                continue
            if max_price not in (None, "") and price > float(max_price):
                continue
            results.append(group)

        ordering_map = {
            "product_name": lambda item: (
                item["product_name"].lower(),
                item["variant_label"].lower(),
            ),
            "category_name": lambda item: item["category_name"].lower(),
            "retail_price": lambda item: float(item["retail_price"] or 0),
            "total_available": lambda item: item["total_available"],
            "status": lambda item: {"out": 0, "low": 1, "ok": 2}.get(item["status"], 9),
        }
        descending = ordering.startswith("-")
        ordering_key = ordering.lstrip("-")
        results.sort(
            key=ordering_map.get(ordering_key, ordering_map["product_name"]),
            reverse=descending,
        )

        count = len(results)
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("page_size", 12)), 1), 500)
        except (TypeError, ValueError):
            page, page_size = 1, 12
        start = (page - 1) * page_size
        results = results[start : start + page_size]

        return ok(
            {"count": count, "results": results},
            message="Stock overview fetched successfully.",
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

    @action(
        detail=False,
        methods=["get"],
        url_path="adjustment-options",
    )
    def adjustment_options(self, request):
        branch_id = request.query_params.get("branch")
        product_id = request.query_params.get("product")
        variant_id = request.query_params.get("variant")

        errors = {}

        if not branch_id:
            errors["branch"] = ["Branch is required."]

        if not product_id:
            errors["product"] = ["Product is required."]

        if errors:
            return Response(
                errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product = Product.objects.get(
                pk=product_id,
                is_deleted=False,
            )
        except Product.DoesNotExist:
            return Response(
                {"product": ["Selected product was not found."]},
                status=status.HTTP_404_NOT_FOUND,
            )

        variant = None

        if product.has_variants:
            if not variant_id:
                return Response(
                    {"variant": ["Select an attribute for this product."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                variant = ProductVariant.objects.get(
                    pk=variant_id,
                    product=product,
                    is_active=True,
                )
            except ProductVariant.DoesNotExist:
                return Response(
                    {
                        "variant": [
                            "Selected attribute does not belong " "to this product."
                        ]
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        stock = (
            ProductStock.objects.select_related(
                "product",
                "variant",
                "branch",
            )
            .filter(
                branch_id=branch_id,
                product=product,
                variant=variant,
            )
            .first()
        )

        regular_quantity = int(getattr(stock, "regular_quantity", 0) or 0)
        reserved_regular_quantity = int(
            getattr(stock, "reserved_regular_quantity", 0) or 0
        )
        available_regular_quantity = max(
            0,
            regular_quantity - reserved_regular_quantity,
        )

        from apps.common.sensitive_permissions import (
            can_view_restricted,
        )

        restricted_allowed = can_view_restricted(request.user)

        restricted_quantity = (
            int(
                getattr(
                    stock,
                    "restricted_quantity",
                    0,
                )
                or 0
            )
            if restricted_allowed
            else 0
        )

        reserved_restricted_quantity = (
            int(
                getattr(
                    stock,
                    "reserved_restricted_quantity",
                    0,
                )
                or 0
            )
            if restricted_allowed
            else 0
        )

        available_restricted_quantity = max(
            0,
            restricted_quantity - reserved_restricted_quantity,
        )

        return Response(
            {
                "success": True,
                "message": ("Stock adjustment options loaded."),
                "data": {
                    "stock_id": (stock.id if stock else None),
                    "product": product.id,
                    "product_name": product.product_name,
                    "sku": product.sku,
                    "variant": (variant.id if variant else None),
                    "variant_label": (variant_label(variant) if variant else ""),
                    "regular_quantity": regular_quantity,
                    "reserved_regular_quantity": (reserved_regular_quantity),
                    "available_regular_quantity": (available_regular_quantity),
                    "restricted_quantity": (restricted_quantity),
                    "reserved_restricted_quantity": (reserved_restricted_quantity),
                    "available_restricted_quantity": (available_restricted_quantity),
                    "restricted_allowed": (restricted_allowed),
                    "average_unit_cost_excluding_vat": (
                        str(stock.average_unit_cost_excluding_vat or 0)
                        if stock
                        else "0.0000"
                    ),
                },
            },
            status=status.HTTP_200_OK,
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
        "stock_classification",
        "vat_treatment",
        "is_vat_relevant",
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
        "net_value_change",
        "running_stock_value",
        "vat_percentage",
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
        "stock_classification",
    ]
    search_fields = [
        "adjustment_number",
        "product__product_name",
        "product__sku",
        "reason",
    ]

    def _signed_quantity(self, adjustment_type, quantity):
        parsed_quantity = int(quantity or 0)

        return parsed_quantity if adjustment_type == "ADD" else -parsed_quantity

    def _get_locked_stock(
        self,
        *,
        product,
        variant,
        branch,
    ):
        stock, _ = ProductStock.objects.select_for_update().get_or_create(
            product=product,
            variant=variant,
            branch=branch,
            defaults={
                "current_stock": 0,
                "regular_quantity": 0,
                "restricted_quantity": 0,
                "reserved_regular_quantity": 0,
                "reserved_restricted_quantity": 0,
            },
        )

        return stock

    def _classification_quantity(
        self,
        stock,
        classification,
    ):
        if classification == "RESTRICTED":
            return int(stock.restricted_quantity or 0)

        return int(stock.regular_quantity or 0)

    def _available_quantity(
        self,
        stock,
        classification,
    ):
        if classification == "RESTRICTED":
            return int(stock.available_restricted_quantity or 0)

        return int(stock.available_regular_quantity or 0)

    def _unit_costs(self, stock):
        unit_cost_excluding_vat = Decimal(
            str(
                stock.average_unit_cost_excluding_vat
                or stock.last_purchase_cost_excluding_vat
                or 0
            )
        )

        capitalized_unit_cost = Decimal(
            str(stock.average_unit_cost or unit_cost_excluding_vat or 0)
        )

        return (
            unit_cost_excluding_vat,
            capitalized_unit_cost,
        )

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user

        branch = serializer.validated_data.get("branch") or getattr(
            user, "branch", None
        )

        if not branch:
            raise ValidationError(
                {"branch": ("Branch is required for a stock adjustment.")}
            )

        product = serializer.validated_data["product"]
        variant = serializer.validated_data.get("variant")
        adjustment_type = serializer.validated_data["adjustment_type"]
        quantity = int(serializer.validated_data["quantity"])
        classification = str(
            serializer.validated_data.get(
                "stock_classification",
                "REGULAR",
            )
        ).upper()

        stock = self._get_locked_stock(
            product=product,
            variant=variant,
            branch=branch,
        )

        current_quantity = self._classification_quantity(
            stock,
            classification,
        )

        available_quantity = self._available_quantity(
            stock,
            classification,
        )

        signed_quantity = self._signed_quantity(
            adjustment_type,
            quantity,
        )

        if signed_quantity < 0 and current_quantity <= 0:
            raise ValidationError(
                {
                    "quantity": (
                        f"No {classification.lower()} stock "
                        "is available for this product "
                        "and attribute."
                    )
                }
            )

        if signed_quantity < 0 and abs(signed_quantity) > available_quantity:
            raise ValidationError(
                {
                    "quantity": (
                        f"Only {available_quantity} "
                        f"{classification.lower()} units "
                        "are available."
                    )
                }
            )

        actual_quantity = current_quantity + signed_quantity

        (
            unit_cost_excluding_vat,
            capitalized_unit_cost,
        ) = self._unit_costs(stock)

        adjustment_number = f"SA-{timezone.now():%Y%m%d%H%M%S%f}"

        adjustment = serializer.save(
            adjustment_number=adjustment_number,
            branch=branch,
            current_quantity=current_quantity,
            actual_quantity_counted=actual_quantity,
            quantity_difference=signed_quantity,
            unit_cost_excluding_vat=(unit_cost_excluding_vat),
            vat_treatment="OUT_OF_SCOPE",
            vat_percentage=Decimal("0.00"),
            value_before=(Decimal(current_quantity) * capitalized_unit_cost),
            value_after=(Decimal(actual_quantity) * capitalized_unit_cost),
            capitalized_adjustment_value=(Decimal(quantity) * capitalized_unit_cost),
            status="APPROVED",
            approved_by=user,
            created_by=user,
            updated_by=user,
        )

        adjust_stock(
            product=product,
            variant=variant,
            branch=branch,
            quantity=signed_quantity,
            movement_type="ADJUSTMENT",
            performed_by=user,
            reference_type="STOCK_ADJUSTMENT",
            reference_id=adjustment.id,
            remarks=(f"{adjustment.reason}. " f"{adjustment.remarks or ''}").strip(),
            stock_classification=classification,
            unit_cost=unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        """
        Reverse the original approved stock effect and apply
        the edited adjustment inside one database transaction.
        """
        user = self.request.user

        # Lock only the StockAdjustment row.
        #
        # Do not combine select_for_update() with select_related("variant")
        # because variant is nullable. PostgreSQL represents that relation
        # with an OUTER JOIN and raises:
        # "FOR UPDATE cannot be applied to the nullable side of an outer join".
        adjustment = StockAdjustment.objects.select_for_update().get(
            pk=serializer.instance.pk
        )

        old_product = adjustment.product
        old_variant = adjustment.variant
        old_branch = adjustment.branch
        old_classification = str(adjustment.stock_classification or "REGULAR").upper()
        old_adjustment_type = str(adjustment.adjustment_type or "").upper()
        old_quantity = int(adjustment.quantity or 0)

        old_signed_quantity = self._signed_quantity(
            old_adjustment_type,
            old_quantity,
        )

        new_product = serializer.validated_data.get(
            "product",
            adjustment.product,
        )
        new_variant = serializer.validated_data.get(
            "variant",
            adjustment.variant,
        )
        new_branch = serializer.validated_data.get(
            "branch",
            adjustment.branch,
        )
        new_classification = str(
            serializer.validated_data.get(
                "stock_classification",
                old_classification,
            )
        ).upper()
        new_adjustment_type = str(
            serializer.validated_data.get(
                "adjustment_type",
                old_adjustment_type,
            )
        ).upper()
        new_quantity = int(
            serializer.validated_data.get(
                "quantity",
                adjustment.quantity,
            )
        )

        new_signed_quantity = self._signed_quantity(
            new_adjustment_type,
            new_quantity,
        )

        old_stock = self._get_locked_stock(
            product=old_product,
            variant=old_variant,
            branch=old_branch,
        )

        same_stock_target = (
            old_product.pk == new_product.pk
            and getattr(old_variant, "pk", None) == getattr(new_variant, "pk", None)
            and old_branch.pk == new_branch.pk
            and old_classification == new_classification
        )

        new_stock = (
            old_stock
            if same_stock_target
            else self._get_locked_stock(
                product=new_product,
                variant=new_variant,
                branch=new_branch,
            )
        )

        available_after_reversal = self._available_quantity(
            new_stock,
            new_classification,
        )

        if same_stock_target:
            available_after_reversal -= old_signed_quantity

        if (
            new_signed_quantity < 0
            and abs(new_signed_quantity) > available_after_reversal
        ):
            raise ValidationError(
                {
                    "quantity": (
                        f"Only {available_after_reversal} "
                        f"{new_classification.lower()} units "
                        "will be available after reversing "
                        "the original adjustment."
                    )
                }
            )

        (
            old_unit_cost_excluding_vat,
            _old_capitalized_unit_cost,
        ) = self._unit_costs(old_stock)

        # Reverse the original inventory effect.
        adjust_stock(
            product=old_product,
            variant=old_variant,
            branch=old_branch,
            quantity=-old_signed_quantity,
            movement_type="ADJUSTMENT",
            performed_by=user,
            reference_type=("STOCK_ADJUSTMENT_EDIT_REVERSAL"),
            reference_id=adjustment.id,
            remarks=(
                "Reversal before editing stock adjustment "
                f"{adjustment.adjustment_number}."
            ),
            stock_classification=old_classification,
            unit_cost=old_unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )

        # Refresh after reversal before calculating new values.
        new_stock.refresh_from_db()

        new_current_quantity = self._classification_quantity(
            new_stock,
            new_classification,
        )

        new_actual_quantity = new_current_quantity + new_signed_quantity

        (
            new_unit_cost_excluding_vat,
            new_capitalized_unit_cost,
        ) = self._unit_costs(new_stock)

        updated_adjustment = serializer.save(
            current_quantity=new_current_quantity,
            actual_quantity_counted=(new_actual_quantity),
            quantity_difference=(new_signed_quantity),
            unit_cost_excluding_vat=(new_unit_cost_excluding_vat),
            vat_treatment="OUT_OF_SCOPE",
            vat_percentage=Decimal("0.00"),
            recoverable_vat_amount=Decimal("0.00"),
            non_recoverable_vat_amount=Decimal("0.00"),
            value_before=(Decimal(new_current_quantity) * new_capitalized_unit_cost),
            value_after=(Decimal(new_actual_quantity) * new_capitalized_unit_cost),
            capitalized_adjustment_value=(
                Decimal(new_quantity) * new_capitalized_unit_cost
            ),
            status="APPROVED",
            approved_by=user,
            updated_by=user,
        )

        # Apply the edited inventory effect.
        adjust_stock(
            product=updated_adjustment.product,
            variant=updated_adjustment.variant,
            branch=updated_adjustment.branch,
            quantity=new_signed_quantity,
            movement_type="ADJUSTMENT",
            performed_by=user,
            reference_type="STOCK_ADJUSTMENT_EDIT",
            reference_id=updated_adjustment.id,
            remarks=(
                f"Edited adjustment "
                f"{updated_adjustment.adjustment_number}. "
                f"{updated_adjustment.reason}. "
                f"{updated_adjustment.remarks or ''}"
            ).strip(),
            stock_classification=(updated_adjustment.stock_classification or "REGULAR"),
            unit_cost=new_unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )


@api_view(["GET"])
def low_stock_products(request):
    queryset = (
        ProductStock.objects.select_related(
            "product",
            "variant",
            "branch",
            "product__brand",
            "product__category",
        )
        .filter(Q(product__has_variants=False) | Q(variant__isnull=False))
        .annotate(
            total_quantity_db=ExpressionWrapper(
                F("regular_quantity") + F("restricted_quantity"),
                output_field=IntegerField(),
            ),
            available_regular_db=ExpressionWrapper(
                F("regular_quantity") - F("reserved_regular_quantity"),
                output_field=IntegerField(),
            ),
            available_restricted_db=ExpressionWrapper(
                F("restricted_quantity") - F("reserved_restricted_quantity"),
                output_field=IntegerField(),
            ),
            total_available_db=ExpressionWrapper(
                F("regular_quantity")
                + F("restricted_quantity")
                - F("reserved_regular_quantity")
                - F("reserved_restricted_quantity"),
                output_field=IntegerField(),
            ),
        )
    )

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
