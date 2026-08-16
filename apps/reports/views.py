from calendar import month_abbr
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.common.branch_access import (
    can_view_all_branches,
    get_user_branch_id,
)
from apps.common.response import ok

ZERO = Decimal("0.00")


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _branch_id(request):
    """
    Respect the active branch selector for users who can view all branches.
    Branch-restricted users are always forced to their assigned branch.
    """
    if not can_view_all_branches(request.user):
        return get_user_branch_id(request.user)

    value = request.query_params.get("branch")

    if value in (None, "", "all", "null", "undefined"):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_param(request, name):
    value = request.query_params.get(name)

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _apply_branch(queryset, branch_id):
    if branch_id:
        return queryset.filter(branch_id=branch_id)

    return queryset


def _apply_date_range(queryset, field_name, date_from=None, date_to=None):
    filters = {}

    if date_from:
        filters[f"{field_name}__gte"] = date_from

    if date_to:
        filters[f"{field_name}__lte"] = date_to

    return queryset.filter(**filters) if filters else queryset


def _month_start(value):
    return value.replace(day=1)


def _shift_month(value, months):
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_dashboard(request):
    from apps.inventory.models import ProductStock
    from apps.purchases.models import PurchaseOrder, SupplierBill
    from apps.sales.models import SalesInvoice

    today = timezone.localdate()
    month_start = today.replace(day=1)
    branch_id = _branch_id(request)

    invoices = _apply_branch(SalesInvoice.objects.all(), branch_id).exclude(
        payment_status="VOID"
    )
    purchase_orders = _apply_branch(
        PurchaseOrder.objects.all(),
        branch_id,
    ).exclude(status="CANCELLED")
    supplier_bills = _apply_branch(
        SupplierBill.objects.all(),
        branch_id,
    ).exclude(status="CANCELLED")
    stocks = _apply_branch(
        ProductStock.objects.select_related("branch"),
        branch_id,
    )

    sales_month = (
        invoices.filter(invoice_date__gte=month_start).aggregate(
            total=Coalesce(
                Sum("total_amount"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    purchases_month = (
        purchase_orders.filter(order_date__gte=month_start).aggregate(
            total=Coalesce(
                Sum("total_amount"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    receivables = (
        invoices.filter(balance_due__gt=0).aggregate(
            total=Coalesce(
                Sum("balance_due"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    payables = (
        supplier_bills.filter(balance_due__gt=0).aggregate(
            total=Coalesce(
                Sum("balance_due"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    valuation_expression = ExpressionWrapper(
        F("current_stock") * F("average_unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=2),
    )

    inventory_value = (
        stocks.aggregate(
            total=Coalesce(
                Sum(valuation_expression),
                ZERO,
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    first_month = _shift_month(_month_start(today), -5)
    sales_by_month = {
        (row["month"].date() if hasattr(row["month"], "date") else row["month"]): row[
            "total"
        ]
        or ZERO
        for row in invoices.filter(invoice_date__gte=first_month)
        .annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(
            total=Coalesce(
                Sum("total_amount"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
    }

    purchases_by_month = {
        (row["month"].date() if hasattr(row["month"], "date") else row["month"]): row[
            "total"
        ]
        or ZERO
        for row in purchase_orders.filter(order_date__gte=first_month)
        .annotate(month=TruncMonth("order_date"))
        .values("month")
        .annotate(
            total=Coalesce(
                Sum("total_amount"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )
    }

    trend = []

    for offset in range(6):
        month = _shift_month(first_month, offset)

        trend.append(
            {
                "month": f"{month_abbr[month.month]} {str(month.year)[-2:]}",
                "sales": sales_by_month.get(month, ZERO),
                "purchases": purchases_by_month.get(month, ZERO),
            }
        )

    return ok(
        {
            "kpi": {
                "sales_month": sales_month,
                "purchases_month": purchases_month,
                "receivables": receivables,
                "payables": payables,
                "inventory_value": inventory_value,
            },
            "trend": trend,
        },
        message="Reports dashboard fetched successfully",
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def purchase_report(request):
    from apps.purchases.models import PurchaseOrder, SupplierBill

    branch_id = _branch_id(request)
    date_from = _date_param(request, "date_from")
    date_to = _date_param(request, "date_to")
    status = request.query_params.get("status")

    queryset = (
        PurchaseOrder.objects.select_related("supplier", "branch")
        .all()
        .order_by("-order_date", "-id")
    )
    queryset = _apply_branch(queryset, branch_id)
    queryset = _apply_date_range(
        queryset,
        "order_date",
        date_from,
        date_to,
    )

    if status and status != "ALL":
        queryset = queryset.filter(status=status)

    bill_queryset = _apply_branch(
        SupplierBill.objects.exclude(status="CANCELLED"),
        branch_id,
    )
    bill_queryset = _apply_date_range(
        bill_queryset,
        "bill_date",
        date_from,
        date_to,
    )

    rows = [
        {
            "id": order.id,
            "po_number": order.po_number,
            "date": order.order_date,
            "supplier": order.supplier.supplier_name,
            "branch": getattr(order.branch, "branch_name", "") if order.branch else "",
            "subtotal": order.subtotal,
            "vat_amount": order.vat_amount,
            "total": order.total_amount,
            "status": order.status,
            "payment_status": order.payment_status,
        }
        for order in queryset
    ]

    total_value = sum((_decimal(row["total"]) for row in rows), ZERO)
    approved_count = sum(
        1
        for row in rows
        if row["status"] in {"APPROVED", "PARTIALLY_RECEIVED", "RECEIVED"}
    )
    outstanding_payables = (
        bill_queryset.filter(balance_due__gt=0).aggregate(
            total=Coalesce(
                Sum("balance_due"),
                ZERO,
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        )["total"]
        or ZERO
    )

    return ok(
        {
            "summary": {
                "orders": len(rows),
                "purchase_value": total_value,
                "approved_orders": approved_count,
                "outstanding_payables": outstanding_payables,
            },
            "rows": rows,
        },
        message="Purchase report fetched successfully",
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inventory_report(request):
    from apps.inventory.models import ProductStock

    branch_id = _branch_id(request)

    queryset = ProductStock.objects.select_related(
        "product",
        "variant",
        "branch",
    ).order_by(
        "branch__branch_name",
        "product__product_name",
        "id",
    )
    queryset = _apply_branch(queryset, branch_id)

    rows = []
    branch_totals = {}

    for stock in queryset:
        unit_cost = _decimal(stock.average_unit_cost)
        stock_value = _decimal(stock.current_stock) * unit_cost
        branch_name = stock.branch.branch_name
        available = max(
            0, int(stock.current_stock or 0) - int(stock.reserved_stock or 0)
        )

        rows.append(
            {
                "id": stock.id,
                "branch": branch_name,
                "product": stock.product.product_name,
                "variant": (
                    ", ".join(
                        f"{key}: {value}"
                        for key, value in (stock.variant.attributes or {}).items()
                    )
                    if stock.variant and not stock.variant.is_base
                    else ("Base" if stock.variant else "")
                ),
                "sku": getattr(stock.product, "sku", ""),
                "current_stock": stock.current_stock,
                "reserved_stock": stock.reserved_stock,
                "available_stock": available,
                "damaged_stock": stock.damaged_stock,
                "reorder_level": stock.reorder_level,
                "average_unit_cost": unit_cost,
                "value": stock_value,
                "low_stock": available <= int(stock.reorder_level or 0),
            }
        )

        branch_totals[branch_name] = branch_totals.get(branch_name, ZERO) + stock_value

    total_value = sum((_decimal(item["value"]) for item in rows), ZERO)
    total_units = sum(int(item["current_stock"] or 0) for item in rows)
    low_stock_items = sum(1 for item in rows if item["low_stock"])

    return ok(
        {
            "summary": {
                "stock_lines": len(rows),
                "total_units": total_units,
                "inventory_value": total_value,
                "low_stock_items": low_stock_items,
            },
            "valuation_by_branch": [
                {
                    "branch": branch,
                    "value": value,
                }
                for branch, value in branch_totals.items()
            ],
            "rows": rows,
        },
        message="Inventory report fetched successfully",
    )
