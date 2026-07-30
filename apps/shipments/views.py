from django.contrib.auth import (
    get_user_model,
)
from rest_framework.decorators import (
    action,
)
from rest_framework.response import (
    Response,
)
from rest_framework.viewsets import (
    ModelViewSet,
)

from apps.branches.models import Branch
from apps.inventory.models import (
    Product,
    Rack,
)
from apps.purchases.models import (
    PurchaseOrder,
)
from apps.suppliers.models import Supplier

from apps.common.response import ok

from .models import (
    Shipment,
    ShipmentItem,
    ShipmentTrackingLog,
)
from .serializers import (
    ShipmentSerializer,
    ShipmentTrackingLogSerializer,
)

from django.db.models import (
    Q,
)

User = get_user_model()


def _choice_options(
    choices,
):
    return [
        {
            "value": value,
            "label": label,
        }
        for value, label in choices
    ]


def _user_display_name(
    user,
):
    full_name = ""

    if hasattr(
        user,
        "get_full_name",
    ):
        full_name = (user.get_full_name() or "").strip()

    return (
        full_name
        or getattr(
            user,
            "display_name",
            "",
        )
        or getattr(
            user,
            "name",
            "",
        )
        or getattr(
            user,
            "username",
            "",
        )
        or getattr(
            user,
            "email",
            "",
        )
        or f"User {user.pk}"
    )


class ShipmentViewSet(
    ModelViewSet,
):
    queryset = Shipment.objects.select_related(
        "purchase_order",
        "supplier",
        "branch",
        "invoice",
        "customer",
        "received_by",
        "delivery_person",
    ).prefetch_related(
        "items__product__brand",
        "items__variant",
        "items__rack",
        "tracking_logs__updated_by",
    )

    serializer_class = ShipmentSerializer

    filterset_fields = [
        "branch",
        "supplier",
        "purchase_order",
        "customer",
        "status",
        "qc_status",
    ]

    search_fields = [
        "shipment_number",
        "tracking_number",
        "container_number",
        "courier",
        "supplier_invoice_number",
        "delivery_note_number",
        "supplier__supplier_name",
        "purchase_order__po_number",
    ]

    ordering_fields = [
        "shipment_number",
        "shipment_date",
        "expected_date",
        "received_date",
        "status",
        "qc_status",
        "created_at",
    ]

    ordering = [
        "-shipment_date",
        "-id",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch")

        if branch_id not in (
            None,
            "",
            "all",
        ):
            queryset = queryset.filter(
                branch_id=branch_id,
            )

        shipment_type = self.request.query_params.get("shipment_type")

        if shipment_type == "PURCHASE":
            queryset = queryset.filter(
                Q(
                    shipment_type="PURCHASE",
                )
                | Q(
                    purchase_order__isnull=False,
                    supplier__isnull=False,
                )
            )
        elif shipment_type:
            queryset = queryset.filter(
                shipment_type=shipment_type,
            )

        return queryset.distinct()

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(
        self,
        request,
    ):
        branch_id = request.query_params.get("branch")

        suppliers = Supplier.objects.filter(
            is_active=True,
        ).order_by(
            "supplier_name",
        )

        branches = Branch.objects.filter(
            is_active=True,
        ).order_by(
            "branch_code",
        )

        orders = (
            PurchaseOrder.objects.select_related(
                "supplier",
                "branch",
            )
            .prefetch_related(
                "items__product__brand",
                "items__variant",
            )
            .exclude(
                status__in=[
                    "RECEIVED",
                    "CANCELLED",
                ],
            )
            .order_by(
                "-order_date",
                "-id",
            )
        )

        products = (
            Product.objects.select_related(
                "brand",
                "category",
            )
            .prefetch_related(
                "variants",
            )
            .filter(
                is_active=True,
            )
            .order_by(
                "product_name",
            )
        )

        racks = (
            Rack.objects.select_related(
                "branch",
            )
            .filter(
                is_active=True,
            )
            .order_by(
                "rack_code",
            )
        )

        if branch_id not in (
            None,
            "",
            "all",
        ):
            orders = orders.filter(
                branch_id=branch_id,
            )

            racks = racks.filter(
                branch_id=branch_id,
            )

        receivers = (
            User.objects.filter(
                is_active=True,
            )
            .select_related(
                "role",
                "branch",
            )
            .order_by(
                "first_name",
                "username",
            )
        )

        if branch_id:
            receivers = receivers.filter(
                branch_id=branch_id,
            ) | receivers.filter(
                is_superuser=True,
            )

        warehouse_options = []

        for branch in branches:
            warehouse_options.append(
                {
                    "value": f"{branch.branch_code} - Main Warehouse",
                    "label": f"{branch.branch_code} - Main Warehouse",
                    "branch_id": branch.id,
                }
            )

        product_options = []

        for product in products:
            variants = []

            for variant in product.variants.all():
                if (
                    getattr(
                        variant,
                        "is_active",
                        True,
                    )
                    is False
                ):
                    continue

                attributes = (
                    getattr(
                        variant,
                        "attributes",
                        {},
                    )
                    or {}
                )

                display_name = (
                    getattr(
                        variant,
                        "display_name",
                        "",
                    )
                    or " / ".join(str(value) for value in attributes.values())
                    or getattr(
                        variant,
                        "sku",
                        "",
                    )
                    or f"Variant {variant.pk}"
                )

                variants.append(
                    {
                        "id": variant.id,
                        "display_name": display_name,
                        "sku": getattr(
                            variant,
                            "sku",
                            "",
                        ),
                        "purchase_price": getattr(
                            variant,
                            "purchase_price",
                            0,
                        ),
                        "is_base": getattr(
                            variant,
                            "is_base",
                            False,
                        ),
                    }
                )

            product_options.append(
                {
                    "id": product.id,
                    "product_name": product.product_name,
                    "sku": getattr(
                        product,
                        "sku",
                        "",
                    ),
                    "brand_name": (
                        getattr(
                            product.brand,
                            "name",
                            "",
                        )
                        if getattr(
                            product,
                            "brand",
                            None,
                        )
                        else ""
                    ),
                    "category_name": (
                        getattr(
                            product.category,
                            "name",
                            "",
                        )
                        if getattr(
                            product,
                            "category",
                            None,
                        )
                        else ""
                    ),
                    "purchase_price": getattr(
                        product,
                        "purchase_price",
                        0,
                    ),
                    "variants": variants,
                }
            )

        order_options = []

        for order in orders:
            order_items = []

            for item in order.items.all():
                product = item.product
                variant = item.variant

                order_items.append(
                    {
                        "id": item.id,
                        "product_id": item.product_id,
                        "variant_id": item.variant_id,
                        "product_name": getattr(
                            product,
                            "product_name",
                            "",
                        ),
                        "sku": (
                            getattr(
                                variant,
                                "sku",
                                "",
                            )
                            if variant
                            else getattr(
                                product,
                                "sku",
                                "",
                            )
                        ),
                        "brand_name": getattr(
                            getattr(
                                product,
                                "brand",
                                None,
                            ),
                            "name",
                            "",
                        ),
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "vat_percentage": getattr(
                            item,
                            "vat_percentage",
                            5,
                        ),
                    }
                )

            order_options.append(
                {
                    "id": order.id,
                    "po_number": order.po_number,
                    "supplier_id": order.supplier_id,
                    "supplier_name": order.supplier.supplier_name,
                    "branch_id": order.branch_id,
                    "branch_code": order.branch.branch_code,
                    "expected_delivery_date": order.expected_delivery_date,
                    "currency": getattr(
                        order,
                        "currency",
                        "AED",
                    ),
                    "status": order.status,
                    "items": order_items,
                }
            )

        return Response(
            {
                "purchase_orders": order_options,
                "suppliers": [
                    {
                        "id": supplier.id,
                        "supplier_code": supplier.supplier_code,
                        "supplier_name": supplier.supplier_name,
                    }
                    for supplier in suppliers
                ],
                "branches": [
                    {
                        "id": branch.id,
                        "branch_code": branch.branch_code,
                        "branch_name": branch.branch_name,
                    }
                    for branch in branches
                ],
                "warehouses": warehouse_options,
                "receivers": [
                    {
                        "id": user.id,
                        "display_name": _user_display_name(
                            user,
                        ),
                        "email": getattr(
                            user,
                            "email",
                            "",
                        ),
                        "role_name": getattr(
                            getattr(
                                user,
                                "role",
                                None,
                            ),
                            "name",
                            "",
                        ),
                        "branch_id": getattr(
                            user,
                            "branch_id",
                            None,
                        ),
                    }
                    for user in receivers.distinct()
                ],
                "products": product_options,
                "racks": [
                    {
                        "id": rack.id,
                        "rack_code": rack.rack_code,
                        "rack_name": getattr(
                            rack,
                            "rack_name",
                            "",
                        ),
                        "branch_id": rack.branch_id,
                        "branch_code": rack.branch.branch_code,
                    }
                    for rack in racks
                ],
                "shipment_types": _choice_options(
                    Shipment.TYPE_CHOICES,
                ),
                "shipment_statuses": _choice_options(
                    Shipment.STATUS_CHOICES,
                ),
                "qc_statuses": _choice_options(
                    Shipment.QC_STATUS_CHOICES,
                ),
                "conditions": _choice_options(
                    ShipmentItem.CONDITION_CHOICES,
                ),
            }
        )

    def perform_create(
        self,
        serializer,
    ):
        serializer.save()

    @action(
        detail=True,
        methods=["post"],
        url_path="update-status",
    )
    def update_status(
        self,
        request,
        pk=None,
    ):
        shipment = self.get_object()

        shipment.status = request.data.get(
            "status",
            shipment.status,
        )

        if shipment.status in [
            "RECEIVED",
            "COMPLETED",
        ]:
            shipment.received_by = request.user

        shipment.save()

        ShipmentTrackingLog.objects.create(
            shipment=shipment,
            status=shipment.status,
            location=request.data.get(
                "location",
                "",
            ),
            remarks=request.data.get(
                "remarks",
                "",
            ),
            updated_by=request.user,
        )

        return ok(
            ShipmentSerializer(
                shipment,
                context={
                    "request": request,
                },
            ).data
        )

    @action(
        detail=True,
        methods=["get"],
    )
    def tracking(
        self,
        request,
        pk=None,
    ):
        return ok(
            ShipmentTrackingLogSerializer(
                self.get_object().tracking_logs.all(),
                many=True,
            ).data
        )
