from decimal import Decimal
from django.db.models import Sum
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from .models import *
from .serializers import *
from .services import confirm_grn
from apps.common.response import ok


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
        "supplier", "branch"
    ).prefetch_related("items__product", "items__variant")
    serializer_class = POSerializer
    filterset_fields = ["branch", "supplier", "status", "payment_status"]
    search_fields = ["po_number", "supplier__supplier_name", "supplier_reference"]
    ordering_fields = [
        "po_number",
        "order_date",
        "expected_delivery_date",
        "total_amount",
        "status",
        "created_at",
    ]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "count": qs.count(),
                "total_value": qs.aggregate(v=Sum("total_amount"))["v"] or 0,
                "pending": qs.exclude(status__in=["RECEIVED", "CANCELLED"]).count(),
                "received": qs.filter(status="RECEIVED").count(),
            }
        )


class GRNViewSet(Base):
    queryset = GoodsReceivedNote.objects.select_related(
        "purchase_order", "supplier", "branch"
    ).prefetch_related("items__product")
    serializer_class = GRNSerializer
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

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return ok(
            GRNSerializer(confirm_grn(self.get_object(), request.user)).data,
            "GRN confirmed successfully",
        )


class SupplierBillViewSet(Base):
    queryset = SupplierBill.objects.select_related(
        "supplier", "purchase_order", "grn", "branch"
    )
    serializer_class = SupplierBillSerializer
    filterset_fields = ["supplier", "payment_status", "branch"]
    search_fields = [
        "bill_number",
        "supplier_invoice_number",
        "supplier__supplier_name",
        "purchase_order__po_number",
    ]


class SupplierPaymentViewSet(Base):
    queryset = SupplierPayment.objects.select_related(
        "supplier", "branch"
    ).prefetch_related("allocations__bill")
    serializer_class = SupplierPaymentSerializer
    filterset_fields = ["supplier", "payment_method", "branch"]
    search_fields = ["payment_number", "supplier__supplier_name", "reference_number"]

    def perform_create(self, serializer):
        serializer.save(
            paid_by=self.request.user,
            created_by=self.request.user,
            updated_by=self.request.user,
            branch=serializer.validated_data.get("branch")
            or getattr(self.request.user, "branch", None),
        )


class SupplierReturnViewSet(Base):
    queryset = SupplierReturn.objects.select_related(
        "supplier", "grn", "branch"
    ).prefetch_related("items__product")
    serializer_class = SupplierReturnSerializer
    filterset_fields = ["supplier", "status", "branch"]
    search_fields = ["return_number", "supplier__supplier_name", "reason"]


class VendorCreditViewSet(Base):
    queryset = VendorCredit.objects.select_related(
        "supplier", "supplier_return", "branch"
    ).prefetch_related("applications__bill")
    serializer_class = VendorCreditSerializer
    filterset_fields = ["supplier", "status", "branch"]
    search_fields = [
        "credit_number",
        "supplier__supplier_name",
        "reason",
        "reference_number",
    ]

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        credit = self.get_object()
        bill = SupplierBill.objects.get(pk=request.data.get("bill"))
        amount = Decimal(str(request.data.get("amount", 0)))
        if amount <= 0 or amount > credit.remaining_amount or amount > bill.balance_due:
            return Response(
                {"detail": "Invalid credit amount."}, status=status.HTTP_400_BAD_REQUEST
            )
        VendorCreditApplication.objects.create(
            vendor_credit=credit, bill=bill, amount=amount
        )
        credit.applied_amount += amount
        credit.remaining_amount -= amount
        credit.status = (
            "APPLIED" if credit.remaining_amount == 0 else "PARTIALLY_APPLIED"
        )
        credit.save(
            update_fields=["applied_amount", "remaining_amount", "status", "updated_at"]
        )
        bill.paid_amount += amount
        bill.balance_due -= amount
        bill.payment_status = "PAID" if bill.balance_due == 0 else "PARTIALLY_PAID"
        bill.save(
            update_fields=["paid_amount", "balance_due", "payment_status", "updated_at"]
        )
        return Response(self.get_serializer(credit).data)


class PurchaseExpenseViewSet(Base):
    queryset = PurchaseExpense.objects.select_related(
        "supplier", "branch", "approved_by"
    )
    serializer_class = PurchaseExpenseSerializer
    filterset_fields = ["category", "branch", "supplier", "status", "payment_method"]
    search_fields = [
        "expense_number",
        "description",
        "vendor_name",
        "supplier__supplier_name",
    ]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "count": qs.count(),
                "total": qs.aggregate(v=Sum("amount"))["v"] or 0,
                "pending": qs.filter(status="PENDING").aggregate(v=Sum("amount"))["v"]
                or 0,
                "paid": qs.filter(status="PAID").aggregate(v=Sum("amount"))["v"] or 0,
            }
        )
