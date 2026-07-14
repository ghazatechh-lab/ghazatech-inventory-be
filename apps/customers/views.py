from decimal import Decimal

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(ModelViewSet):
    queryset = Customer.objects.filter(is_deleted=False)
    serializer_class = CustomerSerializer
    search_fields = ["customer_code", "customer_name", "phone", "email"]
    filterset_fields = ["is_active", "customer_type", "city", "emirate"]

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save()

    @action(detail=True, methods=["get"], url_path="ledger")
    def ledger(self, request, pk=None):
        customer = self.get_object()

        try:
            from apps.finance.models import LedgerEntry

            entries = LedgerEntry.objects.filter(
                customer=customer, ledger_type="Customer"
            ).order_by("-transaction_date", "-id")

            data = [
                {
                    "id": entry.id,
                    "entry_number": entry.entry_number,
                    "transaction_type": entry.transaction_type,
                    "reference_type": entry.reference_type,
                    "reference_id": entry.reference_id,
                    "debit_amount": str(entry.debit_amount),
                    "credit_amount": str(entry.credit_amount),
                    "balance": str(entry.balance),
                    "transaction_date": entry.transaction_date,
                    "remarks": entry.remarks,
                }
                for entry in entries
            ]

        except Exception:
            data = []

        return Response(
            {
                "success": True,
                "message": "Customer ledger fetched successfully",
                "data": data,
            }
        )

    @action(detail=True, methods=["get"], url_path="sales-history")
    def sales_history(self, request, pk=None):
        customer = self.get_object()

        try:
            from apps.sales.models import SalesInvoice

            invoices = SalesInvoice.objects.filter(customer=customer).order_by(
                "-invoice_date", "-id"
            )

            data = [
                {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "invoice_date": invoice.invoice_date,
                    "sale_type": invoice.sale_type,
                    "total_amount": str(invoice.total_amount),
                    "paid_amount": str(invoice.paid_amount),
                    "balance_due": str(invoice.balance_due),
                    "payment_status": invoice.payment_status,
                    "delivery_status": invoice.delivery_status,
                }
                for invoice in invoices
            ]

        except Exception:
            data = []

        return Response(
            {
                "success": True,
                "message": "Customer sales history fetched successfully",
                "data": data,
            }
        )

    @action(detail=True, methods=["get"], url_path="outstanding")
    def outstanding(self, request, pk=None):
        customer = self.get_object()

        total_invoice_amount = Decimal("0.00")
        total_paid_amount = Decimal("0.00")
        balance_due = Decimal("0.00")

        try:
            from apps.sales.models import SalesInvoice

            invoices = SalesInvoice.objects.filter(customer=customer)

            for invoice in invoices:
                total_invoice_amount += invoice.total_amount or Decimal("0.00")
                total_paid_amount += invoice.paid_amount or Decimal("0.00")
                balance_due += invoice.balance_due or Decimal("0.00")

        except Exception:
            pass

        return Response(
            {
                "success": True,
                "message": "Customer outstanding fetched successfully",
                "data": {
                    "customer_id": customer.id,
                    "customer_code": customer.customer_code,
                    "customer_name": customer.customer_name,
                    "credit_limit": str(customer.credit_limit),
                    "opening_balance": str(customer.opening_balance),
                    "total_invoice_amount": str(total_invoice_amount),
                    "total_paid_amount": str(total_paid_amount),
                    "balance_due": str(balance_due),
                },
            }
        )
