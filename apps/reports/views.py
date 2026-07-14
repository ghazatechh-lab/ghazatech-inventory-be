from decimal import Decimal

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum

from apps.common.response import ok


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)

    sales_month = Decimal("0.00")
    purchases_month = Decimal("0.00")
    receivables = Decimal("0.00")
    payables = Decimal("0.00")

    try:
        from apps.sales.models import SalesInvoice

        sales_month = SalesInvoice.objects.filter(
            invoice_date__gte=month_start
        ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        receivables = SalesInvoice.objects.aggregate(total=Sum("balance_due"))[
            "total"
        ] or Decimal("0.00")
    except Exception:
        pass

    try:
        from apps.purchases.models import PurchaseOrder, SupplierBill

        purchases_month = PurchaseOrder.objects.filter(
            order_date__gte=month_start
        ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        payables = SupplierBill.objects.aggregate(total=Sum("balance_due"))[
            "total"
        ] or Decimal("0.00")
    except Exception:
        pass

    trend = [
        {
            "month": "Jan",
            "sales": 0,
            "purchases": 0,
        },
        {
            "month": "Feb",
            "sales": 0,
            "purchases": 0,
        },
        {
            "month": "Mar",
            "sales": 0,
            "purchases": 0,
        },
        {
            "month": "Apr",
            "sales": 0,
            "purchases": 0,
        },
        {
            "month": "May",
            "sales": 0,
            "purchases": 0,
        },
        {
            "month": "Jun",
            "sales": float(sales_month),
            "purchases": float(purchases_month),
        },
    ]

    return ok(
        {
            "kpi": {
                "sales_month": sales_month,
                "purchases_month": purchases_month,
                "receivables": receivables,
                "payables": payables,
            },
            "trend": trend,
        },
        message="Reports dashboard fetched successfully",
    )
