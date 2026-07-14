from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import *
from .serializers import *
from .services import confirm_invoice, add_payment
from apps.common.response import ok


class QuotationViewSet(ModelViewSet):
    queryset = Quotation.objects.all().prefetch_related("items")
    serializer_class = QuotationSerializer
    filterset_fields = ["branch", "customer", "status"]
    search_fields = ["quotation_number"]

    def perform_create(self, s):
        s.save(
            created_by=self.request.user,
            updated_by=self.request.user,
            branch=s.validated_data.get("branch") or self.request.user.branch,
        )

    @action(detail=True, methods=["post"])
    def send(self, r, pk=None):
        q = self.get_object()
        q.status = "SENT"
        q.save()
        return ok(QuotationSerializer(q).data, "Quotation marked as sent")

    @action(detail=True, methods=["post"], url_path="convert-to-invoice")
    def convert_to_invoice(self, r, pk=None):
        return Response(
            {
                "detail": "Create invoice using quotation data; endpoint foundation ready."
            }
        )


class InvoiceViewSet(ModelViewSet):
    queryset = SalesInvoice.objects.all().prefetch_related("items")
    serializer_class = InvoiceSerializer
    filterset_fields = [
        "branch",
        "customer",
        "payment_status",
        "sale_type",
        "is_confirmed",
    ]
    search_fields = ["invoice_number"]

    def perform_create(self, s):
        s.save(
            created_by=self.request.user,
            updated_by=self.request.user,
            branch=s.validated_data.get("branch") or self.request.user.branch,
        )

    @action(detail=True, methods=["post"])
    def confirm(self, r, pk=None):
        return ok(
            InvoiceSerializer(confirm_invoice(self.get_object(), r.user)).data,
            "Invoice confirmed successfully",
        )

    @action(detail=True, methods=["post"])
    def cancel(self, r, pk=None):
        o = self.get_object()
        o.payment_status = "CANCELLED"
        o.save()
        return ok(message="Invoice cancelled")

    @action(detail=True, methods=["post"], url_path="add-payment")
    def add_payment(self, r, pk=None):
        d = r.data.copy()
        d["invoice"] = pk
        d.setdefault("customer", self.get_object().customer_id)
        d.setdefault("branch", self.get_object().branch_id)
        s = SalesPaymentSerializer(data=d)
        s.is_valid(raise_exception=True)
        p = s.save(received_by=r.user, created_by=r.user)
        add_payment(p, r.user)
        return ok(SalesPaymentSerializer(p).data, "Payment added successfully", 201)


class CreditNoteViewSet(ModelViewSet):
    queryset = SalesCreditNote.objects.all()
    serializer_class = SalesCreditNoteSerializer
    filterset_fields = ["branch", "customer", "status"]


class PaymentViewSet(ModelViewSet):
    queryset = SalesPayment.objects.all()
    serializer_class = SalesPaymentSerializer
    filterset_fields = ["branch", "customer", "invoice", "payment_method"]
