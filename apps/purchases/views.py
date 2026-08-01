import json
from pathlib import Path
from decimal import Decimal
from django.db.models import Q, Sum
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from .models import *
from .serializers import *
from .services import confirm_grn
from apps.common.response import ok
from apps.suppliers.models import Supplier
from apps.finance.models import BankAccount, CashRegister
from apps.inventory.models import ProductStock, StockMovement
from apps.branches.models import Branch
from apps.inventory.models import Rack
from apps.common.sensitive_permissions import (
    has_sensitive_permission,
)
from apps.inventory.services import adjust_stock

User = get_user_model()


class Base(ModelViewSet):
    search_fields = []
    ordering_fields = "__all__"
    ordering = ["-id"]

    def perform_create(self, serializer):
        kwargs = {"created_by": self.request.user, "updated_by": self.request.user}
        if hasattr(serializer.Meta.model, "branch"):
            kwargs["branch"] = serializer.validated_data.get("branch") or getattr(
                self.request.user, "branch", None
            )
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class PurchaseOrderViewSet(Base):
    queryset = PurchaseOrder.objects.select_related(
        "supplier",
        "branch",
        "approved_by",
    ).prefetch_related(
        "items__product",
        "items__variant",
    )

    serializer_class = POSerializer

    filterset_fields = [
        "branch",
        "supplier",
        "status",
        "payment_status",
        "currency",
    ]

    search_fields = [
        "po_number",
        "supplier__supplier_name",
        "supplier_reference",
        "branch__branch_name",
        "branch__branch_code",
    ]

    ordering_fields = [
        "po_number",
        "order_date",
        "expected_delivery_date",
        "total_amount",
        "status",
        "payment_status",
        "created_at",
        "supplier__supplier_name",
        "branch__branch_name",
    ]

    @action(
        detail=True,
        methods=["post"],
        url_path="update-status",
    )
    def update_status(self, request, pk=None):
        """Apply controlled Purchase Order status transitions.

        The frontend uses this endpoint for submission, approval, cancellation,
        and receipt-state updates. Approval metadata is managed here rather
        than being accepted from the client.
        """
        purchase_order = self.get_object()
        requested_status = str(request.data.get("status", "")).strip().upper()

        transitions = {
            "DRAFT": {"PENDING_APPROVAL", "CANCELLED"},
            "PENDING_APPROVAL": {"DRAFT", "APPROVED", "CANCELLED"},
            "APPROVED": {"PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"},
            "PARTIALLY_RECEIVED": {"RECEIVED", "CANCELLED"},
            "RECEIVED": set(),
            "CANCELLED": set(),
        }

        if not requested_status:
            raise serializers.ValidationError(
                {"status": "Please select a new purchase order status."}
            )

        valid_statuses = {value for value, _label in PurchaseOrder.STATUS_CHOICES}
        if requested_status not in valid_statuses:
            raise serializers.ValidationError(
                {"status": "The selected purchase order status is invalid."}
            )

        if requested_status == purchase_order.status:
            return Response(
                {
                    "message": "Purchase order is already in this status.",
                    "data": self.get_serializer(purchase_order).data,
                },
                status=status.HTTP_200_OK,
            )

        allowed = transitions.get(purchase_order.status, set())
        if requested_status not in allowed:
            current_label = purchase_order.get_status_display()
            raise serializers.ValidationError(
                {
                    "status": (
                        f"Purchase order cannot change from {current_label} "
                        f"to {dict(PurchaseOrder.STATUS_CHOICES).get(requested_status, requested_status)}."
                    )
                }
            )

        update_fields = ["status", "updated_at"]
        purchase_order.status = requested_status

        if requested_status == "PENDING_APPROVAL":
            purchase_order.submitted_at = timezone.now()
            update_fields.append("submitted_at")

        if requested_status == "APPROVED":
            purchase_order.approved_by = request.user
            purchase_order.approved_at = timezone.now()
            update_fields.extend(["approved_by", "approved_at"])

        purchase_order.updated_by = request.user
        update_fields.append("updated_by")
        purchase_order.save(update_fields=list(dict.fromkeys(update_fields)))

        return Response(
            {
                "message": (
                    "Purchase order approved successfully."
                    if requested_status == "APPROVED"
                    else "Purchase order status updated successfully."
                ),
                "data": self.get_serializer(purchase_order).data,
            },
            status=status.HTTP_200_OK,
        )

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch")

        date_from = self.request.query_params.get("date_from")

        date_to = self.request.query_params.get("date_to")

        if branch_id:
            queryset = queryset.filter(
                branch_id=branch_id,
            )

        if date_from:
            queryset = queryset.filter(
                order_date__gte=date_from,
            )

        if date_to:
            queryset = queryset.filter(
                order_date__lte=date_to,
            )

        return queryset

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(self, request):
        queryset = self.filter_queryset(
            self.get_queryset(),
        )

        today = timezone.localdate()

        month_queryset = queryset.filter(
            order_date__year=today.year,
            order_date__month=today.month,
        )

        open_statuses = [
            "DRAFT",
            "PENDING_APPROVAL",
            "APPROVED",
            "PARTIALLY_RECEIVED",
        ]

        overdue = queryset.filter(
            expected_delivery_date__lt=today,
        ).exclude(
            status__in=[
                "RECEIVED",
                "CANCELLED",
            ],
        )

        return Response(
            {
                "count": queryset.count(),
                "total_purchase_this_month": month_queryset.aggregate(
                    value=Sum(
                        "total_amount",
                    )
                )["value"]
                or 0,
                "awaiting_approval": queryset.filter(
                    status="PENDING_APPROVAL",
                ).count(),
                "open_po_value": queryset.filter(
                    status__in=open_statuses,
                ).aggregate(
                    value=Sum(
                        "total_amount",
                    )
                )["value"]
                or 0,
                "overdue_deliveries": overdue.count(),
            }
        )


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}
MAX_FILE_SIZE = 10 * 1024 * 1024


def choices_as_options(choices):
    return [{"value": value, "label": label} for value, label in choices]


def user_name(user):
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()

    return (
        full_name
        or getattr(user, "display_name", "")
        or getattr(user, "username", "")
        or getattr(user, "email", "")
        or f"User {user.pk}"
    )


class GRNViewSet(Base):
    queryset = GoodsReceivedNote.objects.select_related(
        "purchase_order",
        "supplier",
        "branch",
        "received_by",
    ).prefetch_related(
        "items__product",
        "items__variant",
        "items__rack",
        "attachments",
        "purchase_order__items",
    )
    serializer_class = GRNSerializer
    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]
    filterset_fields = [
        "branch",
        "supplier",
        "status",
        "is_confirmed",
        "purchase_order",
    ]
    search_fields = [
        "grn_number",
        "purchase_order__po_number",
        "supplier__supplier_name",
    ]
    ordering_fields = [
        "grn_number",
        "received_date",
        "status",
        "created_at",
        "supplier__supplier_name",
        "branch__branch_name",
    ]

    def _request_payload(self, request):
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raise serializers.ValidationError({"payload": "Invalid GRN payload."})
        return request.data

    def _save_attachments(self, grn, request):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: unsupported file type."}
                )

            if file.size > MAX_FILE_SIZE:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: file exceeds 10 MB."}
                )

            GRNAttachment.objects.create(
                grn=grn,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=file.content_type or "",
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=self._request_payload(request))
        serializer.is_valid(raise_exception=True)
        grn = serializer.save()
        self._save_attachments(grn, request)

        output = self.get_serializer(grn)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=self._request_payload(request),
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        grn = serializer.save()
        self._save_attachments(grn, request)
        return Response(self.get_serializer(grn).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")

        orders = (
            PurchaseOrder.objects.select_related(
                "supplier",
                "branch",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
                "shipments",
            )
            .filter(
                status__in=[
                    "APPROVED",
                    "PARTIALLY_RECEIVED",
                ]
            )
            .order_by(
                "-order_date",
                "-id",
            )
        )

        if branch_id not in (None, "", "all"):
            orders = orders.filter(branch_id=branch_id)

        branches = Branch.objects.filter(
            is_active=True,
        ).order_by("branch_code")

        racks = Rack.objects.filter(
            is_active=True,
        ).select_related("branch")

        if branch_id not in (None, "", "all"):
            racks = racks.filter(branch_id=branch_id)

        receivers = User.objects.filter(
            is_active=True,
        ).order_by(
            "first_name",
            "username",
        )

        if branch_id not in (None, "", "all"):
            receivers = receivers.filter(
                Q(branch_id=branch_id) | Q(branch__isnull=True)
            )

        order_options = []

        for order in orders:
            order_items = []

            for item in order.items.all():
                regular_quantity = int(
                    getattr(
                        item,
                        "regular_quantity",
                        0,
                    )
                    or 0
                )

                restricted_quantity = int(
                    getattr(
                        item,
                        "restricted_quantity",
                        0,
                    )
                    or 0
                )

                total_ordered_quantity = int(
                    getattr(
                        item,
                        "quantity",
                        0,
                    )
                    or 0
                )

                # Backward compatibility for old purchase-order records.
                # When classified values are empty, treat the aggregate
                # PO quantity as regular quantity.
                if (
                    regular_quantity == 0
                    and restricted_quantity == 0
                    and total_ordered_quantity > 0
                ):
                    regular_quantity = total_ordered_quantity

                received_regular_quantity = int(
                    getattr(
                        item,
                        "received_regular_quantity",
                        0,
                    )
                    or 0
                )

                received_restricted_quantity = int(
                    getattr(
                        item,
                        "received_restricted_quantity",
                        0,
                    )
                    or 0
                )

                aggregate_received_quantity = int(
                    getattr(
                        item,
                        "received_quantity",
                        0,
                    )
                    or 0
                )

                # Backward compatibility for GRNs created before classified
                # received quantities were introduced.
                if (
                    received_regular_quantity == 0
                    and received_restricted_quantity == 0
                    and aggregate_received_quantity > 0
                ):
                    received_regular_quantity = min(
                        aggregate_received_quantity,
                        regular_quantity,
                    )

                    remaining_aggregate_received = max(
                        0,
                        aggregate_received_quantity - received_regular_quantity,
                    )

                    received_restricted_quantity = min(
                        remaining_aggregate_received,
                        restricted_quantity,
                    )

                remaining_regular_quantity = max(
                    0,
                    regular_quantity - received_regular_quantity,
                )

                remaining_restricted_quantity = max(
                    0,
                    restricted_quantity - received_restricted_quantity,
                )

                remaining_total_quantity = (
                    remaining_regular_quantity + remaining_restricted_quantity
                )

                if remaining_total_quantity <= 0:
                    continue

                order_items.append(
                    {
                        "id": item.id,
                        "po_item_id": item.id,
                        "product_id": item.product_id,
                        "variant_id": item.variant_id,
                        "product_name": (item.product.product_name),
                        "sku": (
                            getattr(
                                item.variant,
                                "sku",
                                "",
                            )
                            if item.variant
                            else getattr(
                                item.product,
                                "sku",
                                "",
                            )
                        ),
                        # Aggregate quantities retained for old frontend code.
                        "quantity": total_ordered_quantity,
                        "ordered_quantity": (regular_quantity + restricted_quantity),
                        "received_quantity": (
                            received_regular_quantity + received_restricted_quantity
                        ),
                        "previously_received_quantity": (
                            received_regular_quantity + received_restricted_quantity
                        ),
                        "remaining_quantity": (remaining_total_quantity),
                        # Classified ordered quantities.
                        "regular_quantity": (regular_quantity),
                        "restricted_quantity": (restricted_quantity),
                        "ordered_regular_quantity": (regular_quantity),
                        "ordered_restricted_quantity": (restricted_quantity),
                        # Classified previously received quantities.
                        "received_regular_quantity": (received_regular_quantity),
                        "received_restricted_quantity": (received_restricted_quantity),
                        "previously_received_regular_quantity": (
                            received_regular_quantity
                        ),
                        "previously_received_restricted_quantity": (
                            received_restricted_quantity
                        ),
                        # Classified remaining quantities.
                        "remaining_regular_quantity": (remaining_regular_quantity),
                        "remaining_restricted_quantity": (
                            remaining_restricted_quantity
                        ),
                    }
                )

            if not order_items:
                continue

            shipment = order.shipments.first() if hasattr(order, "shipments") else None

            order_options.append(
                {
                    "id": order.id,
                    "po_number": order.po_number,
                    "supplier_id": order.supplier_id,
                    "supplier_name": (order.supplier.supplier_name),
                    "branch_id": order.branch_id,
                    "branch_name": (order.branch.branch_name),
                    "currency": getattr(
                        order,
                        "currency",
                        "AED",
                    ),
                    "total_amount": order.total_amount,
                    "shipment_number": (shipment.shipment_number if shipment else ""),
                    "items": order_items,
                }
            )

        return Response(
            {
                "purchase_orders": order_options,
                "branches": [
                    {
                        "id": branch.id,
                        "branch_code": (branch.branch_code),
                        "branch_name": (branch.branch_name),
                    }
                    for branch in branches
                ],
                "receivers": [
                    {
                        "id": user.id,
                        "display_name": user_name(user),
                    }
                    for user in receivers
                ],
                "racks": [
                    {
                        "id": rack.id,
                        "rack_code": (rack.rack_code),
                        "rack_name": getattr(
                            rack,
                            "rack_name",
                            "",
                        ),
                        "branch_id": rack.branch_id,
                    }
                    for rack in racks
                ],
                "quality_statuses": choices_as_options(
                    GoodsReceivedItem.QUALITY_CHOICES
                ),
            }
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        grn = self.get_object()

        if grn.is_confirmed:
            return Response(
                self.get_serializer(grn).data,
                status=status.HTTP_200_OK,
            )

        confirmed = confirm_grn(grn, request.user)
        confirmed.status = "CONFIRMED"
        confirmed.is_confirmed = True
        confirmed.confirmed_at = timezone.now()
        confirmed.save(
            update_fields=[
                "status",
                "is_confirmed",
                "confirmed_at",
                "updated_at",
            ]
        )

        return Response(
            self.get_serializer(confirmed).data,
            status=status.HTTP_200_OK,
        )


ALLOWED_BILL_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}
MAX_BILL_ATTACHMENT_SIZE = 10 * 1024 * 1024


class SupplierBillViewSet(Base):
    queryset = SupplierBill.objects.select_related(
        "supplier",
        "purchase_order",
        "grn",
        "branch",
    ).prefetch_related(
        "items",
        "attachments",
    )

    serializer_class = SupplierBillSerializer

    filterset_fields = [
        "supplier",
        "status",
        "branch",
        "purchase_order",
        "grn",
    ]

    search_fields = [
        "bill_number",
        "supplier_invoice_number",
        "supplier__supplier_name",
        "purchase_order__po_number",
        "grn__grn_number",
    ]
    ordering_fields = [
        "bill_number",
        "bill_date",
        "due_date",
        "total_amount",
        "balance_due",
        "status",
        "created_at",
        "supplier__supplier_name",
    ]
    ordering = ["-bill_date", "-id"]

    def _payload(self, request):
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raise serializers.ValidationError(
                    {"payload": "Invalid supplier bill payload."}
                )
        return request.data

    def _save_attachments(self, bill, request):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_BILL_ATTACHMENT_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: unsupported file type."}
                )

            if file.size > MAX_BILL_ATTACHMENT_SIZE:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: file exceeds 10 MB."}
                )

            SupplierBillAttachment.objects.create(
                bill=bill,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=file.content_type or "",
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=self._payload(request))
        serializer.is_valid(raise_exception=True)
        bill = serializer.save(
            created_by=request.user if request.user.is_authenticated else None,
            updated_by=request.user if request.user.is_authenticated else None,
        )
        self._save_attachments(bill, request)
        return Response(
            self.get_serializer(bill).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=self._payload(request),
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        bill = serializer.save(
            updated_by=request.user if request.user.is_authenticated else None,
        )
        self._save_attachments(bill, request)
        return Response(self.get_serializer(bill).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")
        include_all_branches = str(
            request.query_params.get("include_all_branches", "")
        ).lower() in {"1", "true", "yes"}

        purchase_orders = (
            PurchaseOrder.objects.select_related("supplier", "branch")
            .prefetch_related("items")
            .filter(
                status__in=[
                    "APPROVED",
                    "PARTIALLY_RECEIVED",
                    "RECEIVED",
                ]
            )
            .order_by("-order_date", "-id")
        )

        grns = (
            GoodsReceivedNote.objects.select_related(
                "purchase_order",
                "supplier",
                "branch",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
            )
            .filter(is_confirmed=True)
            .order_by("-received_date", "-id")
        )

        # Supplier Bills follow a PO-first workflow. By default the form may
        # request all eligible POs so a global branch override does not hide
        # valid references. Once a PO is selected, its branch is populated in
        # the bill automatically.
        if branch_id and not include_all_branches:
            purchase_orders = purchase_orders.filter(branch_id=branch_id)
            grns = grns.filter(branch_id=branch_id)

        po_options = [
            {
                "id": po.id,
                "po_number": po.po_number,
                "supplier_id": po.supplier_id,
                "supplier_name": po.supplier.supplier_name,
                "branch_id": po.branch_id,
                "branch_name": po.branch.branch_name,
                "currency": getattr(po, "currency", "AED"),
                "total_amount": po.total_amount,
                "item_count": po.items.count(),
            }
            for po in purchase_orders
        ]

        grn_options = []

        for grn in grns:
            payment_terms = getattr(
                grn.supplier,
                "payment_terms_days",
                0,
            )

            credit_limit = getattr(
                grn.supplier,
                "credit_limit",
                0,
            )

            outstanding = getattr(
                grn.supplier,
                "opening_balance",
                0,
            )

            accepted_value = sum(
                (
                    item.accepted_quantity
                    * getattr(
                        item.product,
                        "purchase_price",
                        0,
                    )
                )
                for item in grn.items.all()
            )

            grn_options.append(
                {
                    "id": grn.id,
                    "grn_number": grn.grn_number,
                    "purchase_order_id": grn.purchase_order_id,
                    "supplier_id": grn.supplier_id,
                    "supplier_name": grn.supplier.supplier_name,
                    "branch_id": grn.branch_id,
                    "branch_name": grn.branch.branch_name,
                    "currency": getattr(
                        grn.purchase_order,
                        "currency",
                        "AED",
                    ),
                    "payment_terms_days": payment_terms,
                    "supplier_credit_limit": credit_limit,
                    "supplier_outstanding": outstanding,
                    "total_accepted_quantity": sum(
                        item.accepted_quantity for item in grn.items.all()
                    ),
                    "receipt_status": (
                        "FULL_RECEIPT"
                        if grn.purchase_order.status == "RECEIVED"
                        else "PARTIAL_RECEIPT"
                    ),
                    "accepted_value": accepted_value,
                    "items": [
                        {
                            "id": item.id,
                            "product_id": item.product_id,
                            "variant_id": item.variant_id,
                            "product_name": item.product.product_name,
                            "sku": (
                                getattr(item.variant, "sku", "")
                                if item.variant
                                else getattr(item.product, "sku", "")
                            ),
                            "accepted_quantity": item.accepted_quantity,
                            "unit_cost": next(
                                (
                                    po_item.unit_price
                                    for po_item in grn.purchase_order.items.all()
                                    if po_item.product_id == item.product_id
                                    and po_item.variant_id == item.variant_id
                                ),
                                0,
                            ),
                            "vat_percentage": next(
                                (
                                    getattr(po_item, "vat_percentage", 5)
                                    for po_item in grn.purchase_order.items.all()
                                    if po_item.product_id == item.product_id
                                    and po_item.variant_id == item.variant_id
                                ),
                                5,
                            ),
                        }
                        for item in grn.items.all()
                        if item.accepted_quantity > 0
                    ],
                }
            )

        return Response(
            {
                "purchase_orders": po_options,
                "grns": grn_options,
            }
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()

        total_payable = (
            queryset.exclude(
                status__in=[
                    "PAID",
                    "CANCELLED",
                ]
            ).aggregate(
                value=Sum("balance_due")
            )["value"]
            or 0
        )

        overdue = (
            queryset.filter(
                due_date__lt=today,
            )
            .exclude(
                status__in=[
                    "PAID",
                    "CANCELLED",
                ]
            )
            .aggregate(value=Sum("balance_due"))["value"]
            or 0
        )

        bills_this_month = queryset.filter(
            bill_date__year=today.year,
            bill_date__month=today.month,
        ).count()

        return Response(
            {
                "total_payable": total_payable,
                "overdue": overdue,
                "bills_this_month": bills_this_month,
            }
        )


ALLOWED_PAYMENT_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}

MAX_PAYMENT_ATTACHMENT_SIZE = 10 * 1024 * 1024


class SupplierPaymentViewSet(Base):
    queryset = SupplierPayment.objects.select_related(
        "supplier",
        "branch",
        "bank_account",
        "cash_register",
    ).prefetch_related(
        "allocations__bill",
        "attachments",
    )

    serializer_class = SupplierPaymentSerializer

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    filterset_fields = [
        "branch",
        "supplier",
        "payment_method",
    ]

    search_fields = [
        "payment_number",
        "supplier__supplier_name",
        "reference_number",
        "cheque_number",
        "allocations__bill__bill_number",
    ]

    ordering_fields = [
        "payment_number",
        "payment_date",
        "amount",
        "payment_method",
        "created_at",
        "supplier__supplier_name",
    ]

    ordering = [
        "-payment_date",
        "-id",
    ]

    def _payload(self, request):
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                raise serializers.ValidationError(
                    {"payload": "Invalid supplier payment payload."}
                )

        return request.data

    def _save_attachments(
        self,
        payment,
        request,
    ):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_PAYMENT_ATTACHMENT_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: unsupported file type."}
                )

            if file.size > MAX_PAYMENT_ATTACHMENT_SIZE:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: file exceeds 10 MB."}
                )

            SupplierPaymentAttachment.objects.create(
                payment=payment,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=file.content_type or "",
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

    @transaction.atomic
    def create(
        self,
        request,
        *args,
        **kwargs,
    ):
        serializer = self.get_serializer(
            data=self._payload(
                request,
            )
        )

        serializer.is_valid(
            raise_exception=True,
        )

        payment = serializer.save()

        self._save_attachments(
            payment,
            request,
        )

        return Response(
            self.get_serializer(
                payment,
            ).data,
            status=status.HTTP_201_CREATED,
        )

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

        supplier_id = request.query_params.get("supplier")

        suppliers = Supplier.objects.filter(
            is_deleted=False,
            is_active=True,
        ).order_by(
            "supplier_name",
        )

        bills = (
            SupplierBill.objects.select_related(
                "supplier",
                "branch",
            )
            .filter(
                balance_due__gt=0,
            )
            .exclude(
                status__in=[
                    "PAID",
                    "CANCELLED",
                ]
            )
            .order_by(
                "due_date",
                "bill_number",
            )
        )

        bank_accounts = BankAccount.objects.filter(
            is_active=True,
        ).order_by(
            "account_name",
        )

        cash_registers = CashRegister.objects.exclude(
            status__in=["CLOSED", "INACTIVE"],
        ).order_by(
            "-register_date",
            "-id",
        )

        if branch_id:
            bills = bills.filter(
                branch_id=branch_id,
            )

            if hasattr(
                BankAccount,
                "branch",
            ):
                bank_accounts = bank_accounts.filter(
                    branch_id=branch_id,
                )

            if hasattr(
                CashRegister,
                "branch",
            ):
                cash_registers = cash_registers.filter(
                    branch_id=branch_id,
                )

        if supplier_id:
            bills = bills.filter(
                supplier_id=supplier_id,
            )

        today = timezone.localdate()

        return Response(
            {
                "suppliers": [
                    {
                        "id": supplier.id,
                        "supplier_code": supplier.supplier_code,
                        "supplier_name": supplier.supplier_name,
                    }
                    for supplier in suppliers
                ],
                "bills": [
                    {
                        "id": bill.id,
                        "bill_number": bill.bill_number,
                        "supplier_id": bill.supplier_id,
                        "supplier_name": bill.supplier.supplier_name,
                        "due_date": bill.due_date,
                        "balance_due": bill.balance_due,
                        "status": bill.status,
                        "display_status": (
                            "OVERDUE"
                            if (bill.due_date < today and bill.balance_due > 0)
                            else bill.status
                        ),
                    }
                    for bill in bills
                ],
                "bank_accounts": [
                    {
                        "id": account.id,
                        "account_name": getattr(
                            account,
                            "account_name",
                            str(account),
                        ),
                    }
                    for account in bank_accounts
                ],
                "cash_registers": [
                    {
                        "id": register.id,
                        "name": (
                            f"Cash Register #{register.id} - "
                            f"{register.register_date} ({register.status})"
                        ),
                        "branch": register.branch_id,
                        "status": register.status,
                    }
                    for register in cash_registers
                ],
            }
        )


ALLOWED_RETURN_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}

MAX_RETURN_ATTACHMENT_SIZE = 10 * 1024 * 1024


class SupplierReturnViewSet(Base):
    queryset = SupplierReturn.objects.select_related(
        "supplier",
        "grn",
        "grn__purchase_order",
        "branch",
        "approved_by",
        "vendor_credit",
    ).prefetch_related(
        "items__product",
        "items__variant",
        "items__grn_item",
        "attachments",
    )

    serializer_class = SupplierReturnSerializer

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    filterset_fields = [
        "supplier",
        "status",
        "branch",
        "reason",
        "resolution",
        "grn",
    ]

    search_fields = [
        "return_number",
        "supplier__supplier_name",
        "grn__grn_number",
        "grn__purchase_order__po_number",
        "reason",
        "details",
    ]

    ordering_fields = [
        "return_number",
        "return_date",
        "total_amount",
        "status",
        "reason",
        "created_at",
        "supplier__supplier_name",
    ]

    ordering = [
        "-return_date",
        "-id",
    ]

    def _payload(self, request):
        """
        Support both normal JSON requests and multipart requests
        containing a JSON string under the payload field.
        """
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise serializers.ValidationError(
                    {"payload": ("Invalid supplier return payload.")}
                ) from exc

        return request.data

    def _save_attachments(
        self,
        supplier_return,
        request,
    ):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_RETURN_ATTACHMENT_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": (f"{file.name}: unsupported file type.")}
                )

            if file.size > MAX_RETURN_ATTACHMENT_SIZE:
                raise serializers.ValidationError(
                    {"attachments": (f"{file.name}: file exceeds 10 MB.")}
                )

            SupplierReturnAttachment.objects.create(
                supplier_return=supplier_return,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=(file.content_type or ""),
                uploaded_by=(request.user if request.user.is_authenticated else None),
            )

    @transaction.atomic
    def create(
        self,
        request,
        *args,
        **kwargs,
    ):
        serializer = self.get_serializer(
            data=self._payload(request),
        )

        serializer.is_valid(raise_exception=True)

        supplier_return = serializer.save(
            created_by=request.user,
            updated_by=request.user,
        )

        self._save_attachments(
            supplier_return,
            request,
        )

        return Response(
            self.get_serializer(supplier_return).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def update(
        self,
        request,
        *args,
        **kwargs,
    ):
        partial = kwargs.pop(
            "partial",
            False,
        )

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=self._payload(request),
            partial=partial,
        )

        serializer.is_valid(raise_exception=True)

        supplier_return = serializer.save(
            updated_by=request.user,
        )

        self._save_attachments(
            supplier_return,
            request,
        )

        return Response(self.get_serializer(supplier_return).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        can_view_restricted = has_sensitive_permission(
            request.user,
            "view_restricted_purchase",
        )

        can_return_restricted = has_sensitive_permission(
            request.user,
            "create_restricted_purchase",
        )

        grns = (
            GoodsReceivedNote.objects.select_related(
                "supplier",
                "branch",
                "purchase_order",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
                "purchase_order__items",
            )
            .filter(
                is_confirmed=True,
            )
            .order_by(
                "-received_date",
                "-id",
            )
        )

        branch_id = request.query_params.get("branch")

        if branch_id not in (
            None,
            "",
            "all",
        ):
            grns = grns.filter(branch_id=branch_id)

        grn_options = []

        for grn in grns:
            returnable_items = []

            po_items = {
                (
                    item.product_id,
                    item.variant_id,
                ): item
                for item in grn.purchase_order.items.all()
            }

            for grn_item in grn.items.all():
                previous_returns = SupplierReturnItem.objects.filter(
                    grn_item=grn_item,
                    supplier_return__status__in=[
                        "PENDING_APPROVAL",
                        "APPROVED",
                        "CREDIT_ISSUED",
                    ],
                ).aggregate(
                    regular=Sum("regular_quantity"),
                    restricted=Sum("restricted_quantity"),
                )

                accepted_regular = int(
                    getattr(
                        grn_item,
                        "regular_accepted_quantity",
                        0,
                    )
                    or 0
                )

                accepted_restricted = int(
                    getattr(
                        grn_item,
                        "restricted_accepted_quantity",
                        0,
                    )
                    or 0
                )

                # Backward compatibility for GRNs created before
                # classified accepted quantities were introduced.
                if (
                    accepted_regular == 0
                    and accepted_restricted == 0
                    and int(grn_item.accepted_quantity or 0) > 0
                ):
                    accepted_regular = int(grn_item.accepted_quantity or 0)

                returned_regular = int(previous_returns["regular"] or 0)

                returned_restricted = int(previous_returns["restricted"] or 0)

                available_regular = max(
                    0,
                    accepted_regular - returned_regular,
                )

                available_restricted = max(
                    0,
                    accepted_restricted - returned_restricted,
                )

                visible_total = available_regular

                if can_view_restricted:
                    visible_total += available_restricted

                if visible_total <= 0:
                    continue

                po_item = po_items.get(
                    (
                        grn_item.product_id,
                        grn_item.variant_id,
                    )
                )

                item_data = {
                    "id": grn_item.id,
                    "grn_item_id": grn_item.id,
                    "product_id": (grn_item.product_id),
                    "variant_id": (grn_item.variant_id),
                    "product_name": (grn_item.product.product_name),
                    "sku": (
                        getattr(
                            grn_item.variant,
                            "sku",
                            "",
                        )
                        if grn_item.variant
                        else getattr(
                            grn_item.product,
                            "sku",
                            "",
                        )
                    ),
                    "accepted_regular_quantity": (accepted_regular),
                    "returned_regular_quantity": (returned_regular),
                    "available_regular_quantity": (available_regular),
                    # Compatibility total for older frontend code.
                    "accepted_quantity": (visible_total),
                    "unit_price": (
                        getattr(
                            po_item,
                            "unit_price",
                            0,
                        )
                        if po_item
                        else 0
                    ),
                }

                if can_view_restricted:
                    item_data.update(
                        {
                            "accepted_restricted_quantity": (accepted_restricted),
                            "returned_restricted_quantity": (returned_restricted),
                            "available_restricted_quantity": (available_restricted),
                        }
                    )

                returnable_items.append(item_data)

            if not returnable_items:
                continue

            grn_options.append(
                {
                    "id": grn.id,
                    "grn_number": (grn.grn_number),
                    "supplier_id": (grn.supplier_id),
                    "supplier_name": (grn.supplier.supplier_name),
                    "branch_id": (grn.branch_id),
                    "branch_name": (grn.branch.branch_name),
                    "received_date": (grn.received_date),
                    "po_number": (grn.purchase_order.po_number),
                    "receipt_status": (
                        "FULL_RECEIPT"
                        if (grn.purchase_order.status == "RECEIVED")
                        else "PARTIAL_RECEIPT"
                    ),
                    "items": (returnable_items),
                }
            )

        return Response(
            {
                "grns": grn_options,
                "can_view_restricted": (can_view_restricted),
                "can_return_restricted": (can_return_restricted),
                "reasons": [
                    {
                        "value": value,
                        "label": label,
                    }
                    for value, label in SupplierReturn.REASON_CHOICES
                ],
                "resolutions": [
                    {
                        "value": value,
                        "label": label,
                    }
                    for value, label in SupplierReturn.RESOLUTION_CHOICES
                ],
            }
        )

    @transaction.atomic
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
        supplier_return = self.get_object()

        next_status = (
            str(
                request.data.get(
                    "status",
                    "",
                )
            )
            .strip()
            .upper()
        )

        valid_statuses = dict(SupplierReturn.STATUS_CHOICES)

        if next_status not in valid_statuses:
            return Response(
                {"status": ["Select a valid supplier return status."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transitions = {
            "DRAFT": {
                "DRAFT",
                "PENDING_APPROVAL",
                "CANCELLED",
            },
            "PENDING_APPROVAL": {
                "PENDING_APPROVAL",
                "REJECTED",
                "CANCELLED",
            },
            "APPROVED": {
                "APPROVED",
            },
            "CREDIT_ISSUED": {
                "CREDIT_ISSUED",
            },
            "REJECTED": {
                "REJECTED",
            },
            "CANCELLED": {
                "CANCELLED",
            },
        }

        allowed_statuses = transitions.get(
            supplier_return.status,
            {
                supplier_return.status,
            },
        )

        if next_status == "APPROVED":
            return Response(
                {"status": ["Use the approve action to approve " "a supplier return."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if next_status not in allowed_statuses:
            current_label = valid_statuses.get(
                supplier_return.status,
                supplier_return.status,
            )
            next_label = valid_statuses.get(
                next_status,
                next_status,
            )

            return Response(
                {
                    "status": [
                        (
                            f"Status cannot be changed from "
                            f"{current_label} to {next_label}."
                        )
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if next_status == supplier_return.status:
            return Response(self.get_serializer(supplier_return).data)

        supplier_return.status = next_status
        supplier_return.updated_by = request.user

        update_fields = [
            "status",
            "updated_by",
            "updated_at",
        ]

        if next_status == "PENDING_APPROVAL":
            supplier_return.submitted_at = timezone.now()
            update_fields.append("submitted_at")

        supplier_return.save(update_fields=update_fields)

        return Response(self.get_serializer(supplier_return).data)

    @transaction.atomic
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        supplier_return = self.get_object()

        if supplier_return.status in {"APPROVED", "CREDIT_ISSUED"}:
            return Response(self.get_serializer(supplier_return).data)

        if supplier_return.status != "PENDING_APPROVAL":
            return Response(
                {"detail": "Only pending supplier returns can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return_items = list(
            supplier_return.items.select_related("product", "variant", "grn_item")
        )

        if not return_items:
            return Response(
                {"detail": "This supplier return has no line items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        restricted_total = sum(
            int(item.restricted_quantity or 0) for item in return_items
        )

        if restricted_total > 0 and not has_sensitive_permission(
            request.user,
            "create_restricted_purchase",
        ):
            return Response(
                {
                    "detail": (
                        "You are not authorized to approve "
                        "a restricted-stock return."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        for item in return_items:
            regular_quantity = int(item.regular_quantity or 0)
            restricted_quantity = int(item.restricted_quantity or 0)

            if regular_quantity > 0:
                adjust_stock(
                    product=item.product,
                    variant=item.variant,
                    branch=supplier_return.branch,
                    quantity=-regular_quantity,
                    movement_type="SUPPLIER_RETURN",
                    stock_classification="REGULAR",
                    performed_by=request.user,
                    reference_type="SUPPLIER_RETURN",
                    reference_id=supplier_return.id,
                    remarks=(
                        f"Regular stock returned under "
                        f"{supplier_return.return_number}."
                    ),
                )

            if restricted_quantity > 0:
                adjust_stock(
                    product=item.product,
                    variant=item.variant,
                    branch=supplier_return.branch,
                    quantity=-restricted_quantity,
                    movement_type="SUPPLIER_RETURN",
                    stock_classification="RESTRICTED",
                    performed_by=request.user,
                    reference_type="SUPPLIER_RETURN",
                    reference_id=supplier_return.id,
                    remarks=(
                        f"Restricted stock returned under "
                        f"{supplier_return.return_number}."
                    ),
                )

        vendor_credit = (
            VendorCredit.objects.select_for_update()
            .filter(supplier_return=supplier_return)
            .first()
        )

        subtotal = sum(
            (
                Decimal(str(item.quantity or 0)) * Decimal(str(item.unit_price or 0))
                for item in return_items
            ),
            Decimal("0.00"),
        )

        if not vendor_credit:
            vendor_credit = VendorCredit.objects.create(
                credit_number=f"VC-{supplier_return.return_number}",
                supplier=supplier_return.supplier,
                supplier_return=supplier_return,
                purchase_order=supplier_return.grn.purchase_order,
                branch=supplier_return.branch,
                credit_date=timezone.localdate(),
                reason="RETURN",
                subtotal=subtotal,
                tax_amount=Decimal("0.00"),
                total_amount=subtotal,
                applied_amount=Decimal("0.00"),
                remaining_amount=subtotal,
                status="OPEN",
                reference_number=supplier_return.return_number,
                notes=(
                    "Created automatically from supplier return "
                    f"{supplier_return.return_number}."
                ),
                created_by=request.user,
                updated_by=request.user,
            )

        vendor_credit.items.all().delete()

        credit_subtotal = Decimal("0.00")
        credit_tax = Decimal("0.00")
        credit_total = Decimal("0.00")

        for return_item in return_items:
            quantity = Decimal(str(return_item.quantity or 0))
            unit_price = Decimal(str(return_item.unit_price or 0))
            tax_percentage = Decimal("0.00")
            line_subtotal = quantity * unit_price
            tax_amount = line_subtotal * tax_percentage / Decimal("100")
            line_total = line_subtotal + tax_amount

            product_name = getattr(
                return_item.product,
                "product_name",
                str(return_item.product),
            )
            sku = (
                getattr(return_item.variant, "sku", "")
                if return_item.variant
                else getattr(return_item.product, "sku", "")
            )
            description = f"{product_name} ({sku})" if sku else product_name

            VendorCreditItem.objects.create(
                vendor_credit=vendor_credit,
                description=description,
                gl_account="Purchase Returns",
                quantity=quantity,
                unit_price=unit_price,
                tax_percentage=tax_percentage,
                tax_amount=tax_amount,
                line_total=line_total,
            )

            credit_subtotal += line_subtotal
            credit_tax += tax_amount
            credit_total += line_total

        applied_amount = vendor_credit.applications.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        vendor_credit.subtotal = credit_subtotal
        vendor_credit.tax_amount = credit_tax
        vendor_credit.total_amount = credit_total
        vendor_credit.applied_amount = applied_amount
        vendor_credit.remaining_amount = max(
            Decimal("0.00"),
            credit_total - applied_amount,
        )
        vendor_credit.status = (
            "FULLY_APPLIED"
            if vendor_credit.remaining_amount == Decimal("0.00")
            else ("PARTIALLY_APPLIED" if applied_amount > Decimal("0.00") else "OPEN")
        )
        vendor_credit.updated_by = request.user
        vendor_credit.save(
            update_fields=[
                "subtotal",
                "tax_amount",
                "total_amount",
                "applied_amount",
                "remaining_amount",
                "status",
                "updated_by",
                "updated_at",
            ]
        )

        supplier_return.status = "CREDIT_ISSUED"
        supplier_return.approved_by = request.user
        supplier_return.approved_at = timezone.now()
        supplier_return.vendor_credit = vendor_credit
        supplier_return.updated_by = request.user
        supplier_return.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "vendor_credit",
                "updated_by",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(supplier_return).data)


ALLOWED_VENDOR_CREDIT_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".eml",
}

MAX_VENDOR_CREDIT_ATTACHMENT_SIZE = 10 * 1024 * 1024


class VendorCreditViewSet(Base):
    queryset = VendorCredit.objects.select_related(
        "supplier",
        "supplier_return",
        "purchase_order",
        "supplier_bill",
        "branch",
        "approved_by",
    ).prefetch_related(
        "items",
        "applications__bill",
        "attachments",
    )

    serializer_class = VendorCreditSerializer

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    filterset_fields = [
        "supplier",
        "status",
        "branch",
        "reason",
        "supplier_return",
        "purchase_order",
        "supplier_bill",
    ]

    search_fields = [
        "credit_number",
        "supplier__supplier_name",
        "reference_number",
        "supplier_return__return_number",
        "purchase_order__po_number",
        "supplier_bill__bill_number",
        "internal_memo",
    ]

    ordering_fields = [
        "credit_number",
        "credit_date",
        "total_amount",
        "applied_amount",
        "remaining_amount",
        "status",
        "reason",
        "created_at",
        "supplier__supplier_name",
    ]

    ordering = [
        "-credit_date",
        "-id",
    ]

    def _payload(self, request):
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                raise serializers.ValidationError(
                    {"payload": "Invalid vendor credit payload."}
                )

        return request.data

    def _save_attachments(
        self,
        vendor_credit,
        request,
    ):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_VENDOR_CREDIT_ATTACHMENT_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: unsupported file type."}
                )

            if file.size > MAX_VENDOR_CREDIT_ATTACHMENT_SIZE:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: file exceeds 10 MB."}
                )

            VendorCreditAttachment.objects.create(
                vendor_credit=vendor_credit,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=file.content_type or "",
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

    @transaction.atomic
    def create(
        self,
        request,
        *args,
        **kwargs,
    ):
        serializer = self.get_serializer(
            data=self._payload(
                request,
            )
        )

        serializer.is_valid(
            raise_exception=True,
        )

        save_kwargs = {}

        if request.user.is_authenticated:
            save_kwargs.update(
                created_by=request.user,
                updated_by=request.user,
            )

        vendor_credit = serializer.save(**save_kwargs)

        self._save_attachments(
            vendor_credit,
            request,
        )

        return Response(
            self.get_serializer(
                vendor_credit,
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def update(
        self,
        request,
        *args,
        **kwargs,
    ):
        partial = kwargs.pop(
            "partial",
            False,
        )

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=self._payload(
                request,
            ),
            partial=partial,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        save_kwargs = {}

        if request.user.is_authenticated:
            save_kwargs["updated_by"] = request.user

        vendor_credit = serializer.save(**save_kwargs)

        self._save_attachments(
            vendor_credit,
            request,
        )

        return Response(
            self.get_serializer(
                vendor_credit,
            ).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")
        supplier_id = request.query_params.get("supplier")

        supplier_returns = (
            SupplierReturn.objects.select_related(
                "supplier",
                "branch",
                "grn",
                "grn__purchase_order",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
            )
            .filter(status__in=["APPROVED", "CREDIT_ISSUED"])
            .order_by("-return_date", "-id")
        )

        purchase_orders = (
            PurchaseOrder.objects.select_related("supplier", "branch")
            .exclude(status="CANCELLED")
            .order_by("-order_date", "-id")
        )

        supplier_bills = (
            SupplierBill.objects.select_related(
                "supplier",
                "branch",
                "purchase_order",
            )
            .filter(balance_due__gt=0)
            .exclude(status__in=["DRAFT", "CANCELLED", "PAID"])
            .order_by("due_date", "-id")
        )

        if branch_id not in (None, "", "all"):
            supplier_returns = supplier_returns.filter(branch_id=branch_id)
            purchase_orders = purchase_orders.filter(branch_id=branch_id)
            supplier_bills = supplier_bills.filter(branch_id=branch_id)

        if supplier_id not in (None, "", "all"):
            supplier_returns = supplier_returns.filter(supplier_id=supplier_id)
            purchase_orders = purchase_orders.filter(supplier_id=supplier_id)
            supplier_bills = supplier_bills.filter(supplier_id=supplier_id)

        return Response(
            {
                "supplier_returns": [
                    {
                        "id": item.id,
                        "return_number": item.return_number,
                        "supplier_id": item.supplier_id,
                        "supplier_name": item.supplier.supplier_name,
                        "branch_id": item.branch_id,
                        "branch_name": item.branch.branch_name,
                        "purchase_order_id": (item.grn.purchase_order_id),
                        "po_number": item.grn.purchase_order.po_number,
                        "total_amount": item.total_amount,
                        "items": [
                            {
                                "id": line.id,
                                "product_id": line.product_id,
                                "variant_id": line.variant_id,
                                "product_name": line.product.product_name,
                                "sku": (
                                    getattr(line.variant, "sku", "")
                                    if line.variant
                                    else getattr(line.product, "sku", "")
                                ),
                                "quantity": line.quantity,
                                "regular_quantity": line.regular_quantity,
                                "restricted_quantity": (line.restricted_quantity),
                                "unit_price": line.unit_price,
                                "line_total": line.line_total,
                            }
                            for line in item.items.all()
                        ],
                    }
                    for item in supplier_returns
                ],
                "purchase_orders": [
                    {
                        "id": po.id,
                        "po_number": po.po_number,
                        "supplier_id": po.supplier_id,
                        "branch_id": po.branch_id,
                        "total_amount": po.total_amount,
                        "status": po.status,
                    }
                    for po in purchase_orders
                ],
                "supplier_bills": [
                    {
                        "id": bill.id,
                        "bill_number": bill.bill_number,
                        "supplier_id": bill.supplier_id,
                        "supplier_name": bill.supplier.supplier_name,
                        "branch_id": bill.branch_id,
                        "purchase_order_id": bill.purchase_order_id,
                        "po_number": (
                            bill.purchase_order.po_number if bill.purchase_order else ""
                        ),
                        "bill_date": bill.bill_date,
                        "due_date": bill.due_date,
                        "total_amount": bill.total_amount,
                        "paid_amount": bill.paid_amount,
                        "open_balance": bill.balance_due,
                        "balance_due": bill.balance_due,
                        "status": bill.status,
                    }
                    for bill in supplier_bills
                ],
            }
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(
        self,
        request,
    ):
        queryset = self.filter_queryset(self.get_queryset())

        return Response(
            {
                "all_count": queryset.count(),
                "open_count": queryset.filter(
                    status="OPEN",
                ).count(),
                "partial_count": queryset.filter(
                    status="PARTIALLY_APPLIED",
                ).count(),
                "applied_count": queryset.filter(
                    status="FULLY_APPLIED",
                ).count(),
                "void_count": queryset.filter(
                    status="VOID",
                ).count(),
                "open_balance": (
                    queryset.filter(
                        status__in=[
                            "OPEN",
                            "PARTIALLY_APPLIED",
                        ]
                    ).aggregate(value=Sum("remaining_amount"))["value"]
                    or 0
                ),
            }
        )

    @transaction.atomic
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
        """
        Approve or void a vendor credit without recursively calling another
        ViewSet action. This avoids a second get_object()/queryset resolution
        cycle that can trigger RecursionError in custom Base query filtering.
        """
        vendor_credit = self.get_object()

        requested_status = (
            str(
                request.data.get(
                    "status",
                    "",
                )
            )
            .strip()
            .upper()
        )

        current_status = str(vendor_credit.status or "").strip().upper()

        valid_statuses = dict(VendorCredit.STATUS_CHOICES)

        if requested_status not in valid_statuses:
            return Response(
                {"status": ["Select a valid vendor credit status."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_status == current_status:
            return Response(
                self.get_serializer(vendor_credit).data,
                status=status.HTTP_200_OK,
            )

        if requested_status == "VOID":
            if Decimal(str(vendor_credit.applied_amount or 0)) > Decimal("0.00"):
                return Response(
                    {
                        "detail": (
                            "Applied credits cannot be voided "
                            "until their applications are reversed."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vendor_credit.status = "VOID"
            vendor_credit.voided_at = timezone.now()
            vendor_credit.void_reason = str(
                request.data.get(
                    "reason",
                    "",
                )
                or ""
            ).strip()

            update_fields = [
                "status",
                "voided_at",
                "void_reason",
                "updated_at",
            ]

            if request.user.is_authenticated:
                vendor_credit.updated_by = request.user
                update_fields.append("updated_by")

            vendor_credit.save(update_fields=update_fields)

            vendor_credit.refresh_from_db()

            return Response(
                self.get_serializer(vendor_credit).data,
                status=status.HTTP_200_OK,
            )

        if requested_status != "OPEN":
            return Response(
                {
                    "status": [
                        (
                            "Applied statuses are calculated "
                            "from credit applications and "
                            "cannot be selected manually."
                        )
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if current_status not in {
            "DRAFT",
            "PENDING",
        }:
            return Response(
                {
                    "status": [
                        "Only draft or pending vendor " "credits can be approved."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_amount = Decimal(str(vendor_credit.total_amount or 0))

        applied_total = Decimal("0.00")

        applications = list(vendor_credit.applications.select_related("bill").all())

        for application in applications:
            bill = SupplierBill.objects.select_for_update().get(id=application.bill_id)

            requested_amount = Decimal(str(application.amount or 0))

            open_balance = Decimal(str(bill.balance_due or 0))

            amount = min(
                requested_amount,
                open_balance,
            )

            if amount <= Decimal("0.00"):
                continue

            bill.balance_due = max(
                Decimal("0.00"),
                open_balance - amount,
            )

            bill.paid_amount = max(
                Decimal("0.00"),
                Decimal(str(bill.total_amount or 0)) - bill.balance_due,
            )

            if bill.balance_due == Decimal("0.00"):
                bill.status = "PAID"
            elif bill.paid_amount > Decimal("0.00"):
                bill.status = "PARTIALLY_PAID"
            else:
                bill.status = "UNPAID"

            bill.save(
                update_fields=[
                    "balance_due",
                    "paid_amount",
                    "status",
                    "updated_at",
                ]
            )

            applied_total += amount

        vendor_credit.applied_amount = applied_total

        vendor_credit.remaining_amount = max(
            Decimal("0.00"),
            total_amount - applied_total,
        )

        if vendor_credit.remaining_amount == Decimal("0.00"):
            vendor_credit.status = "FULLY_APPLIED"
        elif applied_total > Decimal("0.00"):
            vendor_credit.status = "PARTIALLY_APPLIED"
        else:
            vendor_credit.status = "OPEN"

        vendor_credit.posted_at = timezone.now()
        vendor_credit.approved_by = request.user
        vendor_credit.approval_date = timezone.localdate()

        update_fields = [
            "applied_amount",
            "remaining_amount",
            "status",
            "posted_at",
            "approved_by",
            "approval_date",
            "updated_at",
        ]

        if request.user.is_authenticated:
            vendor_credit.updated_by = request.user
            update_fields.append("updated_by")

        vendor_credit.save(update_fields=list(dict.fromkeys(update_fields)))

        vendor_credit.refresh_from_db()

        return Response(
            {
                "success": True,
                "message": ("Vendor credit approved successfully."),
                "data": self.get_serializer(vendor_credit).data,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
    )
    def post(
        self,
        request,
        pk=None,
    ):
        vendor_credit = self.get_object()

        if vendor_credit.status != "DRAFT":
            return Response(
                self.get_serializer(
                    vendor_credit,
                ).data
            )

        applied_total = Decimal("0")

        for application in vendor_credit.applications.select_related("bill").all():
            bill = SupplierBill.objects.select_for_update().get(pk=application.bill_id)

            amount = min(
                application.amount,
                bill.balance_due,
            )

            if amount <= 0:
                continue

            bill.balance_due = max(
                Decimal("0"),
                bill.balance_due - amount,
            )

            bill.paid_amount = max(
                Decimal("0"),
                Decimal(str(bill.total_amount or 0)) - bill.balance_due,
            )

            if bill.balance_due == 0:
                bill.status = "PAID"
            elif bill.paid_amount > 0:
                bill.status = "PARTIALLY_PAID"
            else:
                bill.status = "UNPAID"

            bill.save(
                update_fields=[
                    "paid_amount",
                    "balance_due",
                    "status",
                    "updated_at",
                ]
            )

            applied_total += amount

        vendor_credit.applied_amount = applied_total

        vendor_credit.remaining_amount = max(
            Decimal("0"),
            (vendor_credit.total_amount or Decimal("0")) - applied_total,
        )

        if vendor_credit.remaining_amount == 0:
            vendor_credit.status = "FULLY_APPLIED"
        elif applied_total > 0:
            vendor_credit.status = "PARTIALLY_APPLIED"
        else:
            vendor_credit.status = "OPEN"

        vendor_credit.posted_at = timezone.now()

        if request.user.is_authenticated:
            vendor_credit.updated_by = request.user

        if not vendor_credit.approved_by:
            vendor_credit.approved_by = request.user

        if not vendor_credit.approval_date:
            vendor_credit.approval_date = timezone.localdate()

        vendor_credit.save(
            update_fields=[
                "applied_amount",
                "remaining_amount",
                "status",
                "posted_at",
                "approved_by",
                "approval_date",
                "updated_by",
                "updated_at",
            ]
        )

        return Response(
            self.get_serializer(
                vendor_credit,
            ).data
        )

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
    )
    def void(
        self,
        request,
        pk=None,
    ):
        vendor_credit = self.get_object()

        if vendor_credit.applied_amount > 0:
            return Response(
                {
                    "detail": "Applied credits cannot be voided until their applications are reversed."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        vendor_credit.status = "VOID"

        vendor_credit.voided_at = timezone.now()

        vendor_credit.void_reason = request.data.get(
            "reason",
            "",
        )

        vendor_credit.save(
            update_fields=[
                "status",
                "voided_at",
                "void_reason",
                "updated_at",
            ]
        )

        return Response(
            self.get_serializer(
                vendor_credit,
            ).data
        )


ALLOWED_EXPENSE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_EXPENSE_FILE_SIZE = 10 * 1024 * 1024


class PurchaseExpenseViewSet(Base):
    queryset = PurchaseExpense.objects.select_related(
        "branch",
        "bank_account",
        "cash_register",
        "approved_by",
        "rejected_by",
        "created_by",
        "updated_by",
    ).prefetch_related("attachments")

    serializer_class = PurchaseExpenseSerializer
    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    filterset_fields = [
        "branch",
        "category",
        "payment_method",
        "status",
    ]

    search_fields = [
        "expense_number",
        "description",
        "vendor_name",
        "reference_number",
        "notes",
        "branch__branch_name",
    ]

    ordering_fields = [
        "expense_number",
        "description",
        "category",
        "expense_date",
        "amount",
        "payment_method",
        "status",
        "created_at",
        "branch__branch_name",
    ]

    ordering = [
        "-expense_date",
        "-id",
    ]

    def _payload(self, request):
        """
        Accept normal JSON and multipart requests containing a JSON payload.
        """
        if "payload" not in request.data:
            return request.data

        try:
            return json.loads(request.data["payload"])
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise serializers.ValidationError(
                {"payload": ("Invalid expense payload.")}
            ) from exc

    def _save_attachments(
        self,
        expense,
        request,
    ):
        for file in request.FILES.getlist("attachments"):
            extension = Path(file.name).suffix.lower()

            if extension not in ALLOWED_EXPENSE_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": (f"{file.name}: unsupported file type.")}
                )

            if file.size > MAX_EXPENSE_FILE_SIZE:
                raise serializers.ValidationError(
                    {"attachments": (f"{file.name}: file exceeds 10 MB.")}
                )

            PurchaseExpenseAttachment.objects.create(
                expense=expense,
                file=file,
                original_name=file.name,
                file_size=file.size,
                content_type=(file.content_type or ""),
                uploaded_by=(request.user if request.user.is_authenticated else None),
            )

    @transaction.atomic
    def create(
        self,
        request,
        *args,
        **kwargs,
    ):
        serializer = self.get_serializer(
            data=self._payload(request),
        )
        serializer.is_valid(raise_exception=True)

        save_kwargs = {}

        if request.user.is_authenticated:
            save_kwargs.update(
                created_by=request.user,
                updated_by=request.user,
            )

        expense = serializer.save(**save_kwargs)

        self._save_attachments(
            expense,
            request,
        )

        return Response(
            self.get_serializer(expense).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def update(
        self,
        request,
        *args,
        **kwargs,
    ):
        partial = kwargs.pop(
            "partial",
            False,
        )
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=self._payload(request),
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        save_kwargs = {}

        if request.user.is_authenticated:
            save_kwargs["updated_by"] = request.user

        expense = serializer.save(**save_kwargs)

        self._save_attachments(
            expense,
            request,
        )

        return Response(self.get_serializer(expense).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")

        branches = Branch.objects.filter(is_active=True).order_by("branch_name")

        bank_accounts = BankAccount.objects.filter(is_active=True).order_by(
            "account_name"
        )

        cash_registers = CashRegister.objects.exclude(
            status__in=[
                "CLOSED",
                "INACTIVE",
            ],
        ).order_by(
            "-register_date",
            "-id",
        )

        if branch_id not in (
            None,
            "",
            "all",
        ):
            if hasattr(
                BankAccount,
                "branch_id",
            ) or hasattr(
                BankAccount,
                "branch",
            ):
                bank_accounts = bank_accounts.filter(branch_id=branch_id)

            if hasattr(
                CashRegister,
                "branch_id",
            ) or hasattr(
                CashRegister,
                "branch",
            ):
                cash_registers = cash_registers.filter(branch_id=branch_id)

        category_field = PurchaseExpense._meta.get_field("category")

        return Response(
            {
                "categories": [
                    {
                        "value": value,
                        "label": label,
                    }
                    for value, label in category_field.choices
                ],
                "branches": [
                    {
                        "id": branch.id,
                        "branch_name": (branch.branch_name),
                        "branch_code": (branch.branch_code),
                    }
                    for branch in branches
                ],
                "bank_accounts": [
                    {
                        "id": account.id,
                        "account_name": (
                            getattr(
                                account,
                                "account_name",
                                str(account),
                            )
                        ),
                    }
                    for account in bank_accounts
                ],
                "cash_registers": [
                    {
                        "id": register.id,
                        "name": (
                            f"Cash Register "
                            f"#{register.id} - "
                            f"{register.register_date} "
                            f"({register.status})"
                        ),
                        "branch": (
                            getattr(
                                register,
                                "branch_id",
                                None,
                            )
                        ),
                        "status": (register.status),
                    }
                    for register in cash_registers
                ],
                "statuses": [
                    {
                        "value": value,
                        "label": label,
                    }
                    for value, label in PurchaseExpense.STATUS_CHOICES
                ],
                "payment_methods": [
                    {
                        "value": value,
                        "label": label,
                    }
                    for value, label in PurchaseExpense.PAYMENT_METHOD_CHOICES
                ],
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="categories",
    )
    def categories(self, request):
        category_field = PurchaseExpense._meta.get_field("category")

        return Response(
            [
                {
                    "value": value,
                    "label": label,
                }
                for value, label in category_field.choices
            ]
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
    )
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        today = timezone.localdate()

        this_month = queryset.filter(
            expense_date__year=today.year,
            expense_date__month=today.month,
        )

        pending = queryset.filter(status="PENDING")

        paid = this_month.filter(status="PAID")

        top_category = (
            this_month.values("category")
            .annotate(total=Sum("amount"))
            .order_by("-total")
            .first()
        )

        category_labels = dict(PurchaseExpense._meta.get_field("category").choices)

        return Response(
            {
                "this_month_total": (
                    this_month.aggregate(value=Sum("amount"))["value"] or 0
                ),
                "this_month_count": (this_month.count()),
                "pending_total": (pending.aggregate(value=Sum("amount"))["value"] or 0),
                "pending_count": (pending.count()),
                "paid_this_month": (paid.aggregate(value=Sum("amount"))["value"] or 0),
                "paid_count": (paid.count()),
                "top_category": (
                    category_labels.get(
                        top_category["category"],
                        top_category["category"],
                    )
                    if top_category
                    else ""
                ),
                "top_category_total": (top_category["total"] if top_category else 0),
            }
        )

    @transaction.atomic
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
        expense = self.get_object()

        next_status = (
            str(
                request.data.get(
                    "status",
                    "",
                )
            )
            .strip()
            .upper()
        )

        reason = str(
            request.data.get(
                "reason",
                "",
            )
            or ""
        ).strip()

        valid_statuses = dict(PurchaseExpense.STATUS_CHOICES)

        if next_status not in valid_statuses:
            return Response(
                {"status": ["Select a valid expense status."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transitions = {
            "PENDING": {
                "APPROVED",
                "PAID",
                "REJECTED",
                "CANCELLED",
            },
            "APPROVED": {
                "PAID",
                "REJECTED",
                "CANCELLED",
            },
            "PAID": set(),
            "REJECTED": {
                "PENDING",
                "CANCELLED",
            },
            "CANCELLED": {
                "PENDING",
            },
        }

        if next_status == expense.status:
            return Response(self.get_serializer(expense).data)

        if next_status not in transitions.get(
            expense.status,
            set(),
        ):
            return Response(
                {
                    "status": [
                        (
                            f"Status cannot be changed "
                            f"from {expense.status} "
                            f"to {next_status}."
                        )
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if next_status == "REJECTED" and not reason:
            return Response(
                {"reason": ["Rejection reason is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expense.status = next_status

        update_fields = [
            "status",
            "updated_at",
        ]

        if request.user.is_authenticated:
            expense.updated_by = request.user
            update_fields.append("updated_by")

        if next_status == "APPROVED":
            expense.approved_by = request.user
            expense.approved_at = timezone.now()
            update_fields.extend(
                [
                    "approved_by",
                    "approved_at",
                ]
            )

        elif next_status == "PAID":
            if not expense.approved_by:
                expense.approved_by = request.user
                expense.approved_at = timezone.now()
                update_fields.extend(
                    [
                        "approved_by",
                        "approved_at",
                    ]
                )

        elif next_status == "REJECTED":
            expense.rejected_by = request.user
            expense.rejected_at = timezone.now()
            expense.rejection_reason = reason
            update_fields.extend(
                [
                    "rejected_by",
                    "rejected_at",
                    "rejection_reason",
                ]
            )

        elif next_status == "PENDING":
            expense.rejected_by = None
            expense.rejected_at = None
            expense.rejection_reason = ""
            update_fields.extend(
                [
                    "rejected_by",
                    "rejected_at",
                    "rejection_reason",
                ]
            )

        expense.save(update_fields=list(dict.fromkeys(update_fields)))

        return Response(self.get_serializer(expense).data)

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
    )
    def approve(
        self,
        request,
        pk=None,
    ):
        expense = self.get_object()

        if expense.status != "PENDING":
            return Response(
                {"detail": ("Only pending expenses " "can be approved.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expense.status = "APPROVED"
        expense.approved_by = request.user
        expense.approved_at = timezone.now()

        if request.user.is_authenticated:
            expense.updated_by = request.user

        expense.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_by",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(expense).data)

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-paid",
    )
    def mark_paid(
        self,
        request,
        pk=None,
    ):
        expense = self.get_object()

        if expense.status not in {
            "PENDING",
            "APPROVED",
        }:
            return Response(
                {"detail": ("Expense cannot be marked paid.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expense.status = "PAID"

        if not expense.approved_by:
            expense.approved_by = request.user
            expense.approved_at = timezone.now()

        if request.user.is_authenticated:
            expense.updated_by = request.user

        expense.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_by",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(expense).data)
