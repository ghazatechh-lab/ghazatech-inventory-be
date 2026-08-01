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
        supplier_return = self.get_object()

        if supplier_return.status in [
            "APPROVED",
            "CREDIT_ISSUED",
        ]:
            return Response(self.get_serializer(supplier_return).data)

        if supplier_return.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Only pending supplier returns " "can be approved.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        restricted_total = sum(
            int(item.restricted_quantity or 0) for item in supplier_return.items.all()
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

        return_items = list(
            supplier_return.items.select_related(
                "product",
                "variant",
                "grn_item",
            )
        )

        if not return_items:
            return Response(
                {
                    "detail": (
                        "This supplier return does not contain " "any return items."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1. Deduct returned stock from the correct classification.
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
                        "Regular stock returned under "
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
                        "Restricted stock returned under "
                        f"{supplier_return.return_number}."
                    ),
                )

        # 2. Create or update the vendor-credit header.
        credit_number = f"VC-{supplier_return.return_number}"

        vendor_credit = (
            VendorCredit.objects.select_for_update()
            .filter(supplier_return=supplier_return)
            .first()
        )

        if not vendor_credit:
            vendor_credit = VendorCredit.objects.create(
                credit_number=credit_number,
                supplier=supplier_return.supplier,
                supplier_return=supplier_return,
                purchase_order=(supplier_return.grn.purchase_order),
                branch=supplier_return.branch,
                credit_date=timezone.localdate(),
                reason="RETURN",
                subtotal=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                applied_amount=Decimal("0.00"),
                remaining_amount=Decimal("0.00"),
                status="OPEN",
                notes=(
                    "Vendor credit created from supplier "
                    f"return {supplier_return.return_number}."
                ),
                internal_memo=(
                    "Automatically generated when the supplier " "return was approved."
                ),
                created_by=request.user,
                updated_by=request.user,
            )
        else:
            vendor_credit.items.all().delete()

        # 3. Create vendor-credit line items from supplier-return items.
        subtotal = Decimal("0.00")
        tax_amount = Decimal("0.00")
        total_amount = Decimal("0.00")

        for return_item in return_items:
            regular_quantity = int(return_item.regular_quantity or 0)
            restricted_quantity = int(return_item.restricted_quantity or 0)
            quantity = regular_quantity + restricted_quantity

            if quantity <= 0:
                continue

            unit_price = Decimal(str(return_item.unit_price or 0))

            line_subtotal = Decimal(str(quantity)) * unit_price

            # Supplier-return lines currently do not store a
            # separate VAT percentage, so the generated credit
            # line uses zero tax unless you add a mapped VAT field.
            line_tax_percentage = Decimal("0.00")
            line_tax_amount = Decimal("0.00")
            line_total = line_subtotal + line_tax_amount

            description_parts = [
                getattr(
                    return_item.product,
                    "product_name",
                    None,
                )
                or str(return_item.product)
            ]

            if return_item.variant:
                description_parts.append(str(return_item.variant))

            classification_parts = []

            if regular_quantity:
                classification_parts.append(f"Regular: {regular_quantity}")

            if restricted_quantity:
                classification_parts.append(f"Restricted: {restricted_quantity}")

            if classification_parts:
                description_parts.append(f"({', '.join(classification_parts)})")

            VendorCreditItem.objects.create(
                vendor_credit=vendor_credit,
                description=" ".join(description_parts),
                gl_account="Purchase Returns",
                quantity=quantity,
                unit_price=unit_price,
                tax_percentage=line_tax_percentage,
                tax_amount=line_tax_amount,
                line_total=line_total,
            )

            subtotal += line_subtotal
            tax_amount += line_tax_amount
            total_amount += line_total

        if total_amount <= Decimal("0.00"):
            raise serializers.ValidationError(
                {"items": ("The supplier return total must be " "greater than zero.")}
            )

        # 4. Update calculated vendor-credit totals.
        vendor_credit.subtotal = subtotal
        vendor_credit.tax_amount = tax_amount
        vendor_credit.total_amount = total_amount
        vendor_credit.applied_amount = Decimal("0.00")
        vendor_credit.remaining_amount = total_amount
        vendor_credit.status = "OPEN"
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

        # 5. Applications are intentionally not created here.
        #
        # A VendorCreditApplication should only be created when the
        # user explicitly applies this credit to a specific supplier
        # bill. Automatically selecting a bill could apply the credit
        # to the wrong liability.
        #
        # The applications section will remain empty until a bill
        # application is recorded.

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

        vendor_credit = serializer.save()

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

        vendor_credit = serializer.save()

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

        supplier_returns = (
            SupplierReturn.objects.select_related(
                "supplier",
                "branch",
                "grn__purchase_order",
            )
            .prefetch_related(
                "items__product",
                "items__variant",
            )
            .filter(
                status__in=[
                    "APPROVED",
                    "CREDIT_ISSUED",
                ]
            )
            .order_by(
                "-return_date",
                "-id",
            )
        )

        purchase_orders = PurchaseOrder.objects.select_related(
            "supplier",
            "branch",
        ).order_by(
            "-order_date",
            "-id",
        )

        supplier_bills = SupplierBill.objects.select_related(
            "supplier",
            "branch",
        ).order_by(
            "-bill_date",
            "-id",
        )

        open_bills = (
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

        gl_accounts = [
            {
                "id": "INVENTORY_ASSET",
                "account_name": "Inventory Asset",
                "account_code": "INVENTORY_ASSET",
            },
            {
                "id": "PURCHASE_EXPENSE",
                "account_name": "Purchase Expense",
                "account_code": "PURCHASE_EXPENSE",
            },
            {
                "id": "FREIGHT_EXPENSE",
                "account_name": "Freight Expense",
                "account_code": "FREIGHT_EXPENSE",
            },
            {
                "id": "ACCOUNTS_PAYABLE",
                "account_name": "Accounts Payable",
                "account_code": "ACCOUNTS_PAYABLE",
            },
            {
                "id": "OTHER_EXPENSE",
                "account_name": "Other Expense",
                "account_code": "OTHER_EXPENSE",
            },
        ]

        approvers = User.objects.filter(
            is_active=True,
        ).order_by(
            "first_name",
            "username",
        )

        if branch_id:
            supplier_returns = supplier_returns.filter(
                branch_id=branch_id,
            )

            purchase_orders = purchase_orders.filter(
                branch_id=branch_id,
            )

            supplier_bills = supplier_bills.filter(
                branch_id=branch_id,
            )

            open_bills = open_bills.filter(
                branch_id=branch_id,
            )

        if supplier_id:
            supplier_returns = supplier_returns.filter(
                supplier_id=supplier_id,
            )

            purchase_orders = purchase_orders.filter(
                supplier_id=supplier_id,
            )

            supplier_bills = supplier_bills.filter(
                supplier_id=supplier_id,
            )

            open_bills = open_bills.filter(
                supplier_id=supplier_id,
            )

        inventory_account = next(
            (account for account in gl_accounts if account["id"] == "INVENTORY_ASSET"),
            None,
        )

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
                "supplier_returns": [
                    {
                        "id": supplier_return.id,
                        "return_number": supplier_return.return_number,
                        "supplier_id": supplier_return.supplier_id,
                        "supplier_name": supplier_return.supplier.supplier_name,
                        "branch_id": supplier_return.branch_id,
                        "purchase_order_id": supplier_return.grn.purchase_order_id,
                        "details": supplier_return.details,
                        "notes": supplier_return.notes,
                        "total_amount": supplier_return.total_amount,
                        "items": [
                            {
                                "id": item.id,
                                "product_name": item.product.product_name,
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
                                "quantity": item.quantity,
                                "unit_price": item.unit_price,
                            }
                            for item in supplier_return.items.all()
                        ],
                    }
                    for supplier_return in supplier_returns
                ],
                "purchase_orders": [
                    {
                        "id": order.id,
                        "po_number": order.po_number,
                        "supplier_id": order.supplier_id,
                        "supplier_name": order.supplier.supplier_name,
                    }
                    for order in purchase_orders
                ],
                "supplier_bills": [
                    {
                        "id": bill.id,
                        "bill_number": bill.bill_number,
                        "supplier_id": bill.supplier_id,
                        "supplier_name": bill.supplier.supplier_name,
                        "balance_due": bill.balance_due,
                    }
                    for bill in supplier_bills
                ],
                "open_bills": [
                    {
                        "id": bill.id,
                        "bill_number": bill.bill_number,
                        "supplier_id": bill.supplier_id,
                        "due_date": bill.due_date,
                        "balance_due": bill.balance_due,
                    }
                    for bill in open_bills
                ],
                "gl_accounts": gl_accounts,
                "approvers": [
                    {
                        "id": user.id,
                        "display_name": user_name(
                            user,
                        ),
                    }
                    for user in approvers
                ],
                "default_inventory_account_id": (
                    inventory_account["id"] if inventory_account else None
                ),
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

            if bill.balance_due == 0:
                bill.status = "PAID"
            elif bill.paid_amount > 0 or amount > 0:
                bill.status = "PARTIALLY_PAID"

            bill.save(
                update_fields=[
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
        "branch", "bank_account", "cash_register", "approved_by", "rejected_by"
    ).prefetch_related("attachments")
    serializer_class = PurchaseExpenseSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["branch", "category", "payment_method", "status"]
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
    ordering = ["-expense_date", "-id"]

    def _payload(self, request):
        if "payload" in request.data:
            try:
                return json.loads(request.data["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raise serializers.ValidationError(
                    {"payload": "Invalid expense payload."}
                )
        return request.data

    def _save_attachments(self, expense, request):
        for file in request.FILES.getlist("attachments"):
            ext = Path(file.name).suffix.lower()
            if ext not in ALLOWED_EXPENSE_EXTENSIONS:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: unsupported file type."}
                )
            if file.size > MAX_EXPENSE_FILE_SIZE:
                raise serializers.ValidationError(
                    {"attachments": f"{file.name}: file exceeds 10 MB."}
                )
            PurchaseExpenseAttachment.objects.create(
                expense=expense,
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
        expense = serializer.save()
        self._save_attachments(expense, request)
        return Response(
            self.get_serializer(expense).data, status=status.HTTP_201_CREATED
        )

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=self._payload(request), partial=kwargs.pop("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        expense = serializer.save()
        self._save_attachments(expense, request)
        return Response(self.get_serializer(expense).data)

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        branch_id = request.query_params.get("branch")
        branches = Branch.objects.filter(is_active=True).order_by("branch_name")
        bank_accounts = BankAccount.objects.filter(is_active=True).order_by(
            "account_name"
        )
        cash_registers = CashRegister.objects.exclude(
            status__in=["CLOSED", "INACTIVE"],
        ).order_by("-register_date", "-id")
        if branch_id:
            if hasattr(BankAccount, "branch"):
                bank_accounts = bank_accounts.filter(branch_id=branch_id)
            if hasattr(CashRegister, "branch"):
                cash_registers = cash_registers.filter(branch_id=branch_id)
        return Response(
            {
                "categories": [
                    {"value": c.code, "label": c.name, "id": c.id}
                    for c in PurchaseExpenseCategory.objects.filter(is_active=True)
                ]
                or [
                    {"value": v, "label": l}
                    for v, l in PurchaseExpense.CATEGORY_CHOICES
                ],
                "branches": [
                    {
                        "id": b.id,
                        "branch_name": b.branch_name,
                        "branch_code": b.branch_code,
                    }
                    for b in branches
                ],
                "bank_accounts": [
                    {"id": a.id, "account_name": getattr(a, "account_name", str(a))}
                    for a in bank_accounts
                ],
                "cash_registers": [
                    {
                        "id": c.id,
                        "name": (
                            f"Cash Register #{c.id} - "
                            f"{c.register_date} ({c.status})"
                        ),
                        "branch": c.branch_id,
                        "status": c.status,
                    }
                    for c in cash_registers
                ],
            }
        )

    @action(detail=False, methods=["get", "post"], url_path="categories")
    def categories(self, request):
        if request.method == "POST":
            name = str(request.data.get("name", "")).strip()
            if not name:
                raise serializers.ValidationError(
                    {"name": "Category name is required."}
                )
            from django.utils.text import slugify

            base = slugify(name).upper().replace("-", "_")[:50] or "CATEGORY"
            code = base
            suffix = 2
            while PurchaseExpenseCategory.objects.filter(code=code).exists():
                code = f"{base}_{suffix}"
                suffix += 1
            category = PurchaseExpenseCategory.objects.create(name=name, code=code)
            return Response(
                PurchaseExpenseCategorySerializer(category).data,
                status=status.HTTP_201_CREATED,
            )
        categories = PurchaseExpenseCategory.objects.filter(is_active=True)
        return Response(PurchaseExpenseCategorySerializer(categories, many=True).data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()
        month = qs.filter(
            expense_date__year=today.year, expense_date__month=today.month
        )
        pending = qs.filter(status="PENDING")
        paid = month.filter(status="PAID")
        top = (
            month.values("category")
            .annotate(total=Sum("amount"))
            .order_by("-total")
            .first()
        )
        labels = dict(PurchaseExpense.CATEGORY_CHOICES)
        return Response(
            {
                "this_month_total": month.aggregate(value=Sum("amount"))["value"] or 0,
                "this_month_count": month.count(),
                "pending_total": pending.aggregate(value=Sum("amount"))["value"] or 0,
                "pending_count": pending.count(),
                "paid_this_month": paid.aggregate(value=Sum("amount"))["value"] or 0,
                "paid_count": paid.count(),
                "top_category": (
                    labels.get(top["category"], top["category"]) if top else ""
                ),
                "top_category_total": top["total"] if top else 0,
            }
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        expense = self.get_object()
        if expense.status != "PENDING":
            return Response(
                {"detail": "Only pending expenses can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        expense.status = "APPROVED"
        expense.approved_by = request.user
        expense.approved_at = timezone.now()
        expense.save(
            update_fields=["status", "approved_by", "approved_at", "updated_at"]
        )
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        expense = self.get_object()
        if expense.status not in ["PENDING", "APPROVED"]:
            return Response(
                {"detail": "Expense cannot be marked paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        expense.status = "PAID"
        if not expense.approved_by:
            expense.approved_by = request.user
            expense.approved_at = timezone.now()
        expense.save(
            update_fields=["status", "approved_by", "approved_at", "updated_at"]
        )
        return Response(self.get_serializer(expense).data)
