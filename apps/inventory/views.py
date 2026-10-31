from decimal import Decimal

from django.db import transaction
from apps.common.transactions import routed_atomic
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import (
    ModelViewSet,
    ReadOnlyModelViewSet,
)

from apps.common.response import ok

from apps.recovery.services import soft_delete_to_recovery
from .models import (
    Brand,
    Category,
    Product,
    ProductVariant,
    ProductStock,
    RackStockAllocation,
    Rack,
    StockAdjustment,
    StockMovement,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductSerializer,
    ProductVariantSerializer,
    TenantProductSerializer,
    ProductStockSerializer,
    RackSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    variant_label,
)
from .services import adjust_stock, resolve_unit_cost_excluding_vat
from apps.branch_data.services import database_alias_for_branch
from apps.branches.models import Branch
from .permissions import ReferenceDataPermission
from .product_import_export import (
    import_products_from_workbook,
    product_export_response,
)
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework import status
from apps.branches.models import Branch


def _inventory_request_scope(request, *, require_physical=False):
    """Resolve a selected physical branch to its schema, never to public.

    Shared configuration remains on default. Query/body fallbacks support
    existing clients that send branch IDs instead of X-Branch-ID.
    """
    from apps.branch_data.context import get_active_branch_id
    from apps.branch_data.schema_routing import register_branch_connection

    raw = (
        request.query_params.get("branch")
        or request.headers.get("X-Branch-ID")
        or (
            request.data.get("branch")
            if request.method in {"POST", "PUT", "PATCH"}
            and isinstance(request.data, dict)
            else None
        )
        or get_active_branch_id()
    )
    if raw in (None, "", "all", "ALL"):
        if require_physical:
            raise ValidationError({"branch": "Select a physical branch first."})
        return None, None
    try:
        branch = Branch.objects.using("default").get(pk=int(raw), is_active=True)
    except (Branch.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"branch": "Invalid or inactive branch."})
    if branch.tax_mode not in {"VAT", "NON_VAT"}:
        if require_physical:
            raise ValidationError(
                {"branch": "Select a physical VAT or NON-VAT branch."}
            )
        return branch, None
    alias = register_branch_connection(branch.pk, branch.tax_mode)
    return branch, alias


class TenantCatalogMixin:
    """Keep catalog reference operations in the selected tenant schema."""

    def list(self, request, *args, **kwargs):
        branch, alias = _inventory_request_scope(request)
        if branch is not None and alias is None:
            from apps.branch_data.schema_routing import register_branch_connection

            rows = []
            for physical in Branch.objects.using("default").filter(
                is_active=True, tax_mode__in=["VAT", "NON_VAT"]
            ):
                tenant = register_branch_connection(physical.pk, physical.tax_mode)
                for item in self.queryset.using(tenant).all().order_by("name"):
                    record = self.get_serializer(item).data
                    record["source_branch_id"] = physical.pk
                    record["source_branch_name"] = physical.branch_name
                    record["resource_key"] = f"{physical.pk}:{item.pk}"
                    rows.append(record)
            rows.sort(
                key=lambda item: (item["name"].casefold(), item["source_branch_id"])
            )
            try:
                page = max(1, int(request.query_params.get("page", 1)))
                page_size = min(
                    100, max(1, int(request.query_params.get("page_size", 12)))
                )
            except (TypeError, ValueError):
                raise ValidationError({"page": "Invalid pagination parameters."})
            total = len(rows)
            return Response(
                {
                    "count": total,
                    "next": None,
                    "previous": None,
                    "results": rows[(page - 1) * page_size : page * page_size],
                }
            )
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        branch, alias = _inventory_request_scope(self.request)
        if alias is None and self.action in {
            "retrieve",
            "update",
            "partial_update",
            "destroy",
        }:
            raw = self.request.query_params.get("source_branch_id")
            if raw:
                from apps.branch_data.schema_routing import register_branch_connection

                try:
                    physical = Branch.objects.using("default").get(
                        pk=int(raw), is_active=True, tax_mode__in=["VAT", "NON_VAT"]
                    )
                except (ValueError, TypeError, Branch.DoesNotExist):
                    raise ValidationError(
                        {"source_branch_id": "Invalid physical source branch."}
                    )
                alias = register_branch_connection(physical.pk, physical.tax_mode)
        if alias is None:
            # Consolidated catalog is handled separately; never show stale
            # default.public rows as if they were tenant-owned references.
            return self.queryset.none()
        return self.queryset.using(alias).all()

    def perform_create(self, serializer):
        _, alias = _inventory_request_scope(self.request, require_physical=True)
        obj = serializer.Meta.model(**serializer.validated_data)
        obj.save(using=alias)
        serializer.instance = obj

    def perform_update(self, serializer):
        obj = serializer.instance
        alias = serializer.instance._state.db
        if not alias or not alias.startswith("tenant_"):
            raise ValidationError(
                {"branch": "This record must be edited in its source tenant."}
            )
        for field, value in serializer.validated_data.items():
            setattr(obj, field, value)
        obj.save(using=alias)
        serializer.instance = obj

    def perform_destroy(self, instance):
        alias = instance._state.db
        if not alias or not alias.startswith("tenant_"):
            raise ValidationError({"branch": "Source branch is required for deletion."})
        instance.delete(using=alias)


class BrandViewSet(TenantCatalogMixin, ModelViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [ReferenceDataPermission]
    ordering_fields = ["name", "is_active", "created_at"]
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class CategoryViewSet(TenantCatalogMixin, ModelViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [ReferenceDataPermission]
    ordering_fields = ["name", "is_active", "created_at"]
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class RackViewSet(ModelViewSet):
    permission_classes = [ReferenceDataPermission]
    ordering_fields = ["rack_code", "rack_name", "is_active", "created_at"]
    serializer_class = RackSerializer
    search_fields = ["rack_code", "rack_name"]
    filterset_fields = ["is_active"]

    def list(self, request, *args, **kwargs):
        branch, alias = _inventory_request_scope(request)
        if branch is not None and alias is None:
            from apps.branch_data.schema_routing import register_branch_connection

            rows = []
            for physical in Branch.objects.using("default").filter(
                is_active=True, tax_mode__in=["VAT", "NON_VAT"]
            ):
                tenant = register_branch_connection(physical.pk, physical.tax_mode)
                queryset = (
                    Rack.objects.using(tenant)
                    .filter(branch_id=physical.pk)
                    .order_by("rack_code", "pk")
                )
                for rack in queryset:
                    record = RackSerializer(rack, context={"request": request}).data
                    record["source_branch_id"] = physical.pk
                    record["source_branch_name"] = physical.branch_name
                    record["resource_key"] = f"{physical.pk}:{rack.pk}"
                    rows.append(record)
            search = str(request.query_params.get("search") or "").strip().casefold()
            if search:
                rows = [
                    row
                    for row in rows
                    if search in str(row.get("rack_code") or "").casefold()
                    or search in str(row.get("rack_name") or "").casefold()
                    or search in str(row.get("source_branch_name") or "").casefold()
                ]
            active = request.query_params.get("is_active")
            if active is not None and str(active).lower() in ("true", "false"):
                expected = str(active).lower() == "true"
                rows = [row for row in rows if row.get("is_active") == expected]
            rows.sort(
                key=lambda row: (
                    str(row.get("rack_code") or "").casefold(),
                    row["source_branch_id"],
                    row["id"],
                )
            )
            try:
                page = max(1, int(request.query_params.get("page", 1)))
                size = min(100, max(1, int(request.query_params.get("page_size", 12))))
            except (ValueError, TypeError):
                raise ValidationError({"page": "Invalid pagination parameters."})
            total = len(rows)
            return Response(
                {
                    "count": total,
                    "next": None,
                    "previous": None,
                    "results": rows[(page - 1) * size : page * size],
                }
            )
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        branch, alias = _inventory_request_scope(self.request)
        if alias is None:
            return Rack.objects.none()
        return (
            Rack.objects.using(alias)
            .filter(branch_id=branch.pk)
            .select_related("branch")
        )

    def perform_create(self, serializer):
        branch, alias = _inventory_request_scope(self.request, require_physical=True)
        requested = serializer.validated_data.get("branch")
        if requested is not None and requested.pk != branch.pk:
            raise ValidationError(
                {"branch": "Rack must belong to the selected branch."}
            )
        rack = Rack(
            branch_id=branch.pk,
            rack_code=serializer.validated_data["rack_code"],
            rack_name=serializer.validated_data.get("rack_name", ""),
            is_active=serializer.validated_data.get("is_active", True),
        )
        rack.save(using=alias)
        serializer.instance = rack

    def perform_update(self, serializer):
        branch, alias = _inventory_request_scope(self.request, require_physical=True)
        if (
            serializer.validated_data.get("branch")
            and serializer.validated_data["branch"].pk != branch.pk
        ):
            raise ValidationError({"branch": "Cannot move a rack across schemas."})
        rack = serializer.instance
        for key in ("rack_code", "rack_name", "is_active"):
            if key in serializer.validated_data:
                setattr(rack, key, serializer.validated_data[key])
        rack.save(using=alias)

    def perform_destroy(self, instance):
        alias = instance._state.db
        if not alias or not alias.startswith("tenant_"):
            raise ValidationError({"branch": "Source branch is required for deletion."})
        instance.delete(using=alias)


class RackAllocationViewSet(ReadOnlyModelViewSet):
    """Stock-location breakdown; physical stock remains the quantity authority."""

    permission_classes = [ReferenceDataPermission]

    def get_queryset(self):
        return RackStockAllocation.objects.none()

    @action(detail=False, methods=["get", "put"], url_path="for-stock")
    def for_stock(self, request):
        from django.db.models import Sum
        from rest_framework.permissions import SAFE_METHODS

        branch_code = request.query_params.get("branch_code")
        sku = request.query_params.get("sku")
        stock_id = request.query_params.get("stock_id")
        if not (branch_code and sku and stock_id):
            raise ValidationError(
                {"detail": "branch_code, sku and stock_id are required."}
            )
        if branch_code not in ("BR01", "BR02"):
            raise ValidationError({"branch_code": "Choose a physical branch."})
        branch = Branch.objects.using("default").filter(branch_code=branch_code).first()
        if branch is None:
            raise ValidationError({"branch_code": "Branch not found."})
        alias = database_alias_for_branch(branch.id)
        if alias not in ("vat", "non_vat"):
            raise ValidationError(
                {"branch_code": "Unsupported physical branch database."}
            )
        # Reject colliding numeric IDs by verifying SKU against physical stock product.
        with transaction.atomic(using=alias):
            stock = (
                ProductStock.objects.using(alias)
                .select_for_update()
                .select_related("product", "variant")
                .filter(pk=stock_id, branch_id=branch.id)
                .first()
            )
            if stock is None or stock.product.sku.casefold() != str(sku).casefold():
                raise ValidationError(
                    {
                        "stock_id": "Physical stock does not match the requested SKU and branch."
                    }
                )
            if request.method == "PUT":
                if not (
                    request.user
                    and request.user.is_authenticated
                    and request.user.is_superuser
                ):
                    from rest_framework.exceptions import PermissionDenied

                    raise PermissionDenied(
                        "Only administrators may modify rack allocations."
                    )
                items = request.data.get("allocations")
                if not isinstance(items, list):
                    raise ValidationError(
                        {
                            "allocations": "Provide a list of rack_code and quantity pairs."
                        }
                    )
                if len(items) > 200:
                    raise ValidationError({"allocations": "Too many rack assignments."})
                allocations = []
                seen = set()
                for row in items:
                    if not isinstance(row, dict):
                        raise ValidationError({"allocations": "Invalid row."})
                    code = str(row.get("rack_code") or "").strip()
                    amount = row.get("quantity")
                    if (
                        not code
                        or isinstance(amount, bool)
                        or not isinstance(amount, int)
                        or amount < 0
                    ):
                        raise ValidationError(
                            {
                                "allocations": "Each row requires a rack_code and nonnegative integer quantity."
                            }
                        )
                    rack = (
                        Rack.objects.using(alias)
                        .filter(branch_id=branch.id, rack_code=code, is_active=True)
                        .first()
                    )
                    if rack is None or rack.pk in seen:
                        raise ValidationError(
                            {
                                "allocations": "Unknown or duplicate rack for this branch."
                            }
                        )
                    seen.add(rack.pk)
                    allocations.append((rack, amount))
                total = sum(amount for _, amount in allocations)
                if total > stock.current_stock:
                    raise ValidationError(
                        {
                            "allocations": "Rack allocation exceeds physical stock quantity."
                        }
                    )
                # This operation changes locations only, not ProductStock or movement ledger.
                RackStockAllocation.objects.using(alias).filter(
                    stock_id=stock.pk
                ).delete()
                RackStockAllocation.objects.using(alias).bulk_create(
                    [
                        RackStockAllocation(
                            stock_id=stock.pk, rack_id=rack.pk, quantity=amount
                        )
                        for rack, amount in allocations
                    ]
                )
            records = (
                RackStockAllocation.objects.using(alias)
                .filter(stock_id=stock.pk)
                .select_related("rack")
                .order_by("rack__rack_code")
            )
            rows = [
                {
                    "rack_code": item.rack.rack_code,
                    "rack_name": item.rack.rack_name,
                    "quantity": item.quantity,
                }
                for item in records
            ]
            assigned = sum(row["quantity"] for row in rows)
            return Response(
                {
                    "branch_code": branch_code,
                    "sku": stock.product.sku,
                    "stock_id": stock.pk,
                    "physical_quantity": stock.current_stock,
                    "allocated_quantity": assigned,
                    "unallocated_quantity": stock.current_stock - assigned,
                    "allocations": rows,
                }
            )


class ConsolidatedProductReadSerializer(TenantProductSerializer):
    """Read tenant rows without using write-only branch field validation.

    Keep TenantProductSerializer's tenant-aware representation methods, but
    do not call its get_fields() override that requires a physical branch
    in the incoming request (the request here selects Consolidated).
    """

    def get_fields(self):
        return ProductSerializer.get_fields(self)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        alias = instance._state.db
        source_id = self.context.get("source_branch_id") or instance.branch_id
        variants = list(
            ProductVariant.objects.using(alias)
            .filter(product_id=instance.pk)
            .order_by("pk")
        )
        data["variants"] = ProductVariantSerializer(
            variants,
            many=True,
            context={
                "request": self.context.get("request"),
                "source_branch_id": source_id,
            },
        ).data
        stocks = list(
            ProductStock.objects.using(alias)
            .filter(product_id=instance.pk, branch_id=source_id)
            .order_by("pk")
        )
        # Older products may have opening stock but no base variant row.
        # Display their real stock balance without manufacturing a price.
        if not variants and not instance.has_variants and stocks:
            data["variants"] = [
                {
                    "id": None,
                    "attributes": {},
                    "racks": [],
                    "is_base": True,
                    "is_active": True,
                    "purchase_price": None,
                    "retail_price": None,
                    "wholesale_price": None,
                    "minimum_selling_price": None,
                    "current_stock": sum(s.current_stock for s in stocks),
                    "reserved_stock": sum(s.reserved_stock for s in stocks),
                    "available_stock": sum(
                        max(0, s.current_stock - s.reserved_stock) for s in stocks
                    ),
                }
            ]
        data["stocks"] = [
            {
                "id": stock.pk,
                "variant": stock.variant_id,
                "variant_id": stock.variant_id,
                "current_stock": stock.current_stock,
                "reserved_stock": stock.reserved_stock,
                "damaged_stock": stock.damaged_stock,
                "available_stock": max(0, stock.current_stock - stock.reserved_stock),
                "average_unit_cost": str(stock.average_unit_cost),
                "last_purchase_cost": str(stock.last_purchase_cost),
            }
            for stock in stocks
        ]
        data["total_available_qty"] = sum(
            max(0, s.current_stock - s.reserved_stock) for s in stocks
        )
        return data


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
            "variants__racks",
            "stocks",
        )
    )
    serializer_class = TenantProductSerializer
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
        "has_variants",
        "is_active",
    ]

    def list(self, request, *args, **kwargs):
        branch, alias = _inventory_request_scope(request)
        if branch is not None and alias is None:
            from apps.branch_data.schema_routing import register_branch_connection

            rows = []
            search = (request.query_params.get("search") or "").strip()
            brand = request.query_params.get("brand")
            category = request.query_params.get("category")
            for physical in (
                Branch.objects.using("default")
                .filter(is_active=True, tax_mode__in=["VAT", "NON_VAT"])
                .order_by("pk")
            ):
                tenant = register_branch_connection(physical.pk, physical.tax_mode)
                qs = (
                    Product.objects.using(tenant)
                    .filter(branch_id=physical.pk, is_deleted=False)
                    .select_related("brand", "category", "rack", "supplier", "branch")
                    .prefetch_related("variants__racks", "stocks")
                )
                if search:
                    qs = qs.filter(
                        Q(product_name__icontains=search)
                        | Q(sku__icontains=search)
                        | Q(barcode__icontains=search)
                    )
                if brand:
                    qs = qs.filter(brand_id=brand)
                if category:
                    qs = qs.filter(category_id=category)
                for product in qs.order_by("pk"):
                    record = ConsolidatedProductReadSerializer(
                        product,
                        context={"request": request, "source_branch_id": physical.pk},
                    ).data
                    record["source_branch_id"] = physical.pk
                    record["source_branch_name"] = physical.branch_name
                    record["branch_name"] = physical.branch_name
                    record["branch_code"] = physical.branch_code
                    record["resource_key"] = f"{physical.pk}:{product.pk}"
                    rows.append(record)
            rows.sort(
                key=lambda item: (
                    str(item.get("product_name") or "").casefold(),
                    item["source_branch_id"],
                    item["id"],
                )
            )
            try:
                page = max(1, int(request.query_params.get("page", 1)))
                page_size = min(
                    1000, max(1, int(request.query_params.get("page_size", 12)))
                )
            except (TypeError, ValueError):
                raise ValidationError({"page": "Invalid pagination parameters."})
            start = (page - 1) * page_size
            return Response(
                {
                    "count": len(rows),
                    "next": None,
                    "previous": None,
                    "results": rows[start : start + page_size],
                }
            )
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """Read a product from its physical tenant, including consolidated links.

        The frontend should pass ?branch=<source branch id>. For old links
        without that parameter, an ID is resolved only if it is unambiguous.
        """
        from rest_framework.exceptions import NotFound
        from apps.branch_data.schema_routing import register_branch_connection

        product_pk = kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        raw_source = request.query_params.get("branch")
        if raw_source in (None, ""):
            # Old bookmarks and stale frontend builds may omit source branch.
            # When a physical branch is active, prefer its tenant.
            active_branch, active_alias = _inventory_request_scope(request)
            if active_alias is not None:
                sources = [active_branch]
            else:
                sources = list(
                    Branch.objects.using("default")
                    .filter(is_active=True, tax_mode__in=("VAT", "NON_VAT"))
                    .order_by("pk")
                )
        else:
            try:
                sources = [
                    Branch.objects.using("default").get(
                        pk=int(raw_source),
                        is_active=True,
                        tax_mode__in=("VAT", "NON_VAT"),
                    )
                ]
            except (TypeError, ValueError, Branch.DoesNotExist):
                raise ValidationError(
                    {"branch": "Select a valid physical source branch."}
                )

        matches = []
        for source in sources:
            tenant = register_branch_connection(source.pk, source.tax_mode)
            product = (
                Product.objects.using(tenant)
                .filter(pk=product_pk, branch_id=source.pk, is_deleted=False)
                .select_related("brand", "category", "rack", "supplier", "branch")
                .prefetch_related("variants__racks", "stocks")
                .first()
            )
            if product is not None:
                matches.append((source, product))
                if len(matches) > 1:
                    raise ValidationError(
                        {
                            "branch": "This product ID exists in multiple branches. "
                            "Open it from Consolidated Products so its source branch is included."
                        }
                    )
        if not matches:
            raise NotFound("Product not found in the selected physical branch.")

        source, product = matches[0]
        self.check_object_permissions(request, product)
        data = ConsolidatedProductReadSerializer(
            product, context={"request": request, "source_branch_id": source.pk}
        ).data
        data["source_branch_id"] = source.pk
        data["source_branch_name"] = source.branch_name
        data["branch_name"] = source.branch_name
        data["branch_code"] = source.branch_code
        data["resource_key"] = f"{source.pk}:{product.pk}"
        return Response(data)

    def get_queryset(self):
        queryset = super().get_queryset()
        selected_branch, selected_alias = _inventory_request_scope(self.request)
        if selected_alias:
            queryset = queryset.using(selected_alias).filter(
                branch_id=selected_branch.pk
            )
        else:
            # A consolidated branch must not accidentally read legacy public
            # product tables.  Its combined listing needs a separate endpoint.
            return queryset.none()
        branch_id = self.request.query_params.get("branch")
        rack_id = self.request.query_params.get("rack")

        if branch_id:
            try:
                requested_branch = Branch.objects.using("default").get(pk=branch_id)
            except (Branch.DoesNotExist, TypeError, ValueError):
                return queryset.none()

            if requested_branch.tax_mode in {"VAT", "NON_VAT"}:
                queryset = queryset.filter(branch_id=requested_branch.id).distinct()
            else:
                return (
                    queryset.none()
                )  # Combined view requires dedicated aggregation endpoint.

        if rack_id:
            queryset = queryset.filter(variants__racks_id=rack_id).distinct()

        return queryset.order_by("product_name", "pk")

    def perform_destroy(self, obj):
        if not (obj._state.db or "").startswith("tenant_"):
            raise ValidationError({"branch": "A physical source branch is required."})
        reason = (
            self.request.data.get("deletion_reason")
            or self.request.data.get("reason")
            or self.request.headers.get("X-Deletion-Reason")
            or ""
        )
        soft_delete_to_recovery(
            obj,
            user=self.request.user,
            reason=reason,
            request=self.request,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
    )
    def import_products(self, request):
        uploaded_file = request.FILES.get("file")
        branch_id = request.data.get("branch") or request.query_params.get("branch")

        if not uploaded_file:
            raise ValidationError({"file": "Upload the product Excel file."})

        if not branch_id:
            raise ValidationError(
                {"branch": "Select a branch before importing products."}
            )

        from apps.branches.models import Branch

        try:
            branch = Branch.objects.get(pk=branch_id)
        except Branch.DoesNotExist as exc:
            raise ValidationError({"branch": "Selected branch was not found."}) from exc

        products = import_products_from_workbook(
            request=request,
            branch=branch,
            uploaded_file=uploaded_file,
        )

        return ok(
            {
                "created_count": len(products),
                "product_ids": [product.id for product in products],
            },
            message=f"{len(products)} product(s) imported successfully.",
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
    )
    def export_products(self, request):
        queryset = self.filter_queryset(self.get_queryset()).order_by(
            "product_name",
            "id",
        )
        return product_export_response(queryset)


class StockViewSet(ReadOnlyModelViewSet):
    serializer_class = ProductStockSerializer
    filterset_fields = [
        "branch",
        "product",
        "variant",
    ]

    def _base_queryset(self, using=None):
        manager = ProductStock.objects.using(using) if using else ProductStock.objects
        return (
            manager.select_related(
                "product",
                "product__brand",
                "product__category",
                "variant",
                "branch",
            )
            .prefetch_related("product__variants").filter(product__is_active=True, product__is_deleted=False)
            .filter(Q(product__has_variants=False) | Q(variant__isnull=False))
        )

    def get_queryset(self):
        branch, alias = _inventory_request_scope(self.request)
        if alias:
            return self._base_queryset(alias).filter(branch_id=branch.pk)
        # Consolidated aggregation is done in list(), not with a queryset
        # against default/public or the legacy VAT schemas.
        return self._base_queryset("default").none()

    def list(self, request, *args, **kwargs):
        branch, alias = _inventory_request_scope(request)
        if alias:
            queryset = self._base_queryset(alias).filter(branch_id=branch.pk)
        else:
            from apps.branch_data.schema_routing import register_branch_connection

            queryset = []
            for physical in Branch.objects.using("default").filter(
                is_active=True, tax_mode__in=["VAT", "NON_VAT"]
            ):
                tenant = register_branch_connection(physical.pk, physical.tax_mode)
                queryset.extend(
                    list(self._base_queryset(tenant).filter(branch_id=physical.pk))
                )

        branch_id = str(branch.pk) if alias else None
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
        if isinstance(queryset, list):
            if product_id:
                queryset = [
                    row for row in queryset if str(row.product_id) == str(product_id)
                ]
            if category_id:
                queryset = [
                    row
                    for row in queryset
                    if str(row.product.category_id) == str(category_id)
                ]
            if search:
                term = search.lower()
                queryset = [
                    row
                    for row in queryset
                    if term
                    in " ".join(
                        [
                            row.product.product_name or "",
                            row.product.sku or "",
                            row.branch.branch_name or "",
                            row.branch.branch_code or "",
                        ]
                    ).lower()
                ]
        else:
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
            key = (stock.branch_id, stock.product_id, stock.variant_id)
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
                    "inventory_value_excluding_vat": 0,
                    "recoverable_vat_value": 0,
                    "capitalized_vat_value": 0,
                    "total_inventory_value": 0,
                    "average_unit_cost": 0,
                    "vat_treatment": stock.last_tax_treatment,
                    "vat_percentage": stock.last_vat_percentage,
                }

            available = stock.available_stock
            group = groups[key]
            group["branch_stocks"].append(
                {
                    "branch_id": stock.branch_id,
                    "stock_id": stock.pk,
                    "branch_code": stock.branch.branch_code,
                    "branch_name": stock.branch.branch_name,
                    "current_stock": stock.current_stock,
                    "reserved_stock": stock.reserved_stock,
                    "total_quantity": stock.total_quantity,
                    "total_available_quantity": stock.total_available_quantity,
                    "damaged_stock": stock.damaged_stock,
                    "available_stock": available,
                    "average_unit_cost_excluding_vat": resolve_unit_cost_excluding_vat(
                        stock, product=stock.product, variant=stock.variant
                    ),
                    "recoverable_vat_per_unit": stock.recoverable_vat_per_unit,
                    "capitalized_vat_per_unit": stock.capitalized_vat_per_unit,
                    "average_unit_cost": stock.average_unit_cost,
                    "inventory_value_excluding_vat": stock.inventory_value_excluding_vat,
                    "recoverable_vat_value": stock.recoverable_vat_value,
                    "capitalized_vat_value": stock.capitalized_vat_value,
                    "total_inventory_value": stock.total_inventory_value,
                    "vat_treatment": stock.last_tax_treatment,
                    "vat_percentage": stock.last_vat_percentage,
                }
            )
            group["total_current"] += stock.current_stock
            group["total_reserved"] += stock.reserved_stock
            group["total_damaged"] += stock.damaged_stock
            group["total_available"] += available
            group["inventory_value_excluding_vat"] += float(
                stock.inventory_value_excluding_vat
            )
            group["recoverable_vat_value"] += float(stock.recoverable_vat_value)
            group["capitalized_vat_value"] += float(stock.capitalized_vat_value)
            group["total_inventory_value"] += float(stock.total_inventory_value)
            group["average_unit_cost"] = float(
                stock.average_unit_cost
                or resolve_unit_cost_excluding_vat(
                    stock, product=stock.product, variant=stock.variant
                )
                or 0
            )
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

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        return low_stock_products(request)

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

        branch, tenant = _inventory_request_scope(request, require_physical=True)
        if str(branch.id) != str(branch_id):
            raise ValidationError(
                {"branch": "Branch selection does not match request."}
            )
        product = (
            Product.objects.using(tenant)
            .filter(pk=product_id, branch_id=branch.id, is_deleted=False)
            .first()
        )
        if product is None:
            return Response(
                {"product": ["Selected product was not found."]}, status=404
            )
        variant = None
        if product.has_variants:
            if not variant_id:
                return Response({"variant": ["Select a variant."]}, status=400)
            variant = (
                ProductVariant.objects.using(tenant)
                .filter(pk=variant_id, product_id=product.id, is_active=True)
                .first()
            )
            if variant is None:
                return Response(
                    {"variant": ["Variant does not belong to this product."]},
                    status=404,
                )
        stock = (
            ProductStock.objects.using(tenant)
            .filter(
                branch_id=branch.id,
                product_id=product.id,
                variant_id=(variant.id if variant else None),
            )
            .first()
        )

        current_stock = int(getattr(stock, "current_stock", 0) or 0)
        reserved_stock = int(getattr(stock, "reserved_stock", 0) or 0)
        available_stock = max(0, current_stock - reserved_stock)

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
                    "current_stock": current_stock,
                    "reserved_stock": reserved_stock,
                    "available_stock": available_stock,
                    "available_quantity": available_stock,
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
        using = database_alias_for_branch(branch)
        with transaction.atomic(using=using):
            stock, _ = (
                ProductStock.objects.using(using)
                .select_for_update()
                .get_or_create(
                    product_id=product.id,
                    variant_id=(variant.id if variant else None),
                    branch_id=branch.id,
                    defaults={
                        "current_stock": 0,
                        "reserved_stock": 0,
                        "reorder_level": product.reorder_level,
                    },
                )
            )
        return stock

    @staticmethod
    def _current_quantity(stock):
        return int(stock.current_stock or 0)

    @staticmethod
    def _available_quantity(stock):
        return int(stock.available_stock or 0)

    def _unit_costs(self, stock):
        unit_cost_excluding_vat = resolve_unit_cost_excluding_vat(
            stock,
            product=stock.product,
            variant=stock.variant,
        )

        capitalized_unit_cost = Decimal(
            str(stock.average_unit_cost or unit_cost_excluding_vat or 0)
        )

        return (
            unit_cost_excluding_vat,
            capitalized_unit_cost,
        )

    @routed_atomic
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
                "REGULAR",
            )
        ).upper()

        stock = self._get_locked_stock(
            product=product,
            variant=variant,
            branch=branch,
        )

        current_quantity = self._current_quantity(stock)
        available_quantity = self._available_quantity(stock)

        signed_quantity = self._signed_quantity(
            adjustment_type,
            quantity,
        )

        if signed_quantity < 0 and current_quantity <= 0:
            raise ValidationError(
                {"quantity": ("No stock is available for this product and attribute.")}
            )

        if signed_quantity < 0 and abs(signed_quantity) > available_quantity:
            raise ValidationError(
                {"quantity": (f"Only {available_quantity} units are available.")}
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
            unit_cost=unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )

    @routed_atomic
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
        adjustment_db = getattr(
            getattr(serializer.instance, "_state", None), "db", None
        ) or database_alias_for_branch(serializer.instance.branch_id)
        with transaction.atomic(using=adjustment_db):
            adjustment = (
                StockAdjustment.objects.using(adjustment_db)
                .select_for_update()
                .get(pk=serializer.instance.pk)
            )

        old_product = adjustment.product
        old_variant = adjustment.variant
        old_branch = adjustment.branch
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

        available_after_reversal = self._available_quantity(new_stock)

        if same_stock_target:
            available_after_reversal -= old_signed_quantity

        if (
            new_signed_quantity < 0
            and abs(new_signed_quantity) > available_after_reversal
        ):
            raise ValidationError(
                {
                    "quantity": (
                        f"Only {available_after_reversal} units will be available "
                        "after reversing the original adjustment."
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
            unit_cost=old_unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )

        # Refresh after reversal before calculating new values.
        new_stock.refresh_from_db()

        new_current_quantity = self._current_quantity(new_stock)

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
            unit_cost=new_unit_cost_excluding_vat,
            vat_percentage=Decimal("0.00"),
            vat_treatment="OUT_OF_SCOPE",
            vat_recoverable=False,
        )


@api_view(["GET"])
def low_stock_products(request):
    from apps.branch_data.schema_routing import register_branch_connection

    branch, alias = _inventory_request_scope(request)
    physical = (
        [branch]
        if alias
        else list(
            Branch.objects.using("default").filter(
                is_active=True, tax_mode__in=["VAT", "NON_VAT"]
            )
        )
    )
    rows = []
    for physical_branch in physical:
        tenant = register_branch_connection(
            physical_branch.id, physical_branch.tax_mode
        )
        stock_items = (
            ProductStock.objects.using(tenant)
            .select_related(
                "product", "variant", "branch", "product__brand", "product__category"
            )
            .filter(branch_id=physical_branch.id).filter(product__is_active=True, product__is_deleted=False)
            .filter(Q(product__has_variants=False) | Q(variant__isnull=False))
        )
        for item in stock_items:
            if item.available_stock < 10:
                record = ProductStockSerializer(item, context={"request": request}).data
                record["source_branch_id"] = physical_branch.pk
                record["source_branch_name"] = physical_branch.branch_name
                record["resource_key"] = f"{physical_branch.pk}:{item.pk}"
                rows.append(record)
    return ok(rows, message="Low stock products fetched successfully.")


# GHZ_TENANT_ADJUSTMENTS_PATCH_V1
# Keep create/list on the same physical tenant database. Other adjustment
# actions are deliberately left on existing code until their write paths are audited.
from .tenant_adjustments import create_tenant_adjustment, list_tenant_adjustments
StockAdjustmentViewSet.create = create_tenant_adjustment
StockAdjustmentViewSet.list = list_tenant_adjustments
