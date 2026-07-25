import csv
from decimal import Decimal

from django.db.models import Count, Max, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.logging import LoggedModelViewSet as ModelViewSet

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(ModelViewSet):
    serializer_class = CustomerSerializer

    search_fields = [
        "customer_code",
        "customer_name",
        "contact_person",
        "phone",
        "email",
        "trn",
        "trn_number",
        "trade_license",
    ]

    filterset_fields = [
        "is_active",
        "customer_type",
        "category",
        "city",
        "emirate",
    ]

    ordering_fields = [
        "customer_name",
        "created_at",
        "credit_limit",
        "balance_due",
        "last_order_date",
    ]

    ordering = ["customer_name"]

    def get_queryset(self):
        from apps.sales.models import SalesInvoice, SalesOrder

        return Customer.objects.filter(is_deleted=False).annotate(
            order_count=Count(
                "salesorder",
                distinct=True,
            ),
            last_order_date=Max(
                "salesorder__order_date",
            ),
            balance_due=Sum(
                "salesinvoice__balance_due",
            ),
        )

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save(
            update_fields=[
                "is_deleted",
                "deleted_by",
                "updated_at",
            ]
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        from apps.sales.models import SalesInvoice, SalesOrder

        queryset = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()

        return Response(
            {
                "total_customers": queryset.count(),
                "active_this_month": queryset.filter(
                    salesorder__order_date__year=today.year,
                    salesorder__order_date__month=today.month,
                )
                .distinct()
                .count(),
                "total_receivables": (
                    SalesInvoice.objects.filter(
                        customer__in=queryset,
                        balance_due__gt=0,
                    ).aggregate(value=Sum("balance_due"))["value"]
                    or 0
                ),
                "new_leads": queryset.filter(
                    category="LEAD",
                    is_active=True,
                ).count(),
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="customers.csv"'
        writer = csv.writer(response)

        writer.writerow(
            [
                "Customer Code",
                "Customer",
                "Type",
                "Contact Person",
                "Phone",
                "Email",
                "TRN",
                "Trade License",
                "Category",
                "Payment Terms",
                "Credit Limit",
                "Balance Due",
            ]
        )

        for customer in queryset:
            writer.writerow(
                [
                    customer.customer_code,
                    customer.customer_name,
                    customer.get_customer_type_display(),
                    customer.contact_person or "",
                    customer.phone or "",
                    customer.email or "",
                    customer.trn or customer.trn_number or "",
                    customer.trade_license or "",
                    customer.get_category_display(),
                    customer.get_payment_terms_display(),
                    customer.credit_limit or 0,
                    getattr(customer, "balance_due", 0) or 0,
                ]
            )

        return response

    @action(detail=True, methods=["get"], url_path="ledger")
    def ledger(self, request, pk=None):
        customer = self.get_object()

        try:
            from apps.finance.models import LedgerEntry

            entries = LedgerEntry.objects.filter(
                customer=customer,
                ledger_type="Customer",
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
                "message": "Outstanding balance fetched successfully",
                "data": {
                    "total_invoice_amount": total_invoice_amount,
                    "total_paid_amount": total_paid_amount,
                    "balance_due": balance_due,
                },
            }
        )
