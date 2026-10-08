from calendar import month_abbr
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.branches.models import Branch
from apps.common.response import ok
from apps.branch_data.workforce_flow import active_interface_branch

ZERO = Decimal("0.00")
PHYSICAL = {"BR01": "vat", "BR02": "non_vat"}


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _date_param(request, name):
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


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


def _physical_rows():
    return {
        b.branch_code.upper(): b
        for b in Branch.objects.using("default").filter(
            is_active=True, branch_code__in=["BR01", "BR02"]
        )
    }


def _requested_source(request):
    raw = str(request.query_params.get("source_branch") or "ALL").upper().replace("-", "_")
    mapping = {"ALL": None, "BR01": "BR01", "VAT": "BR01", "BR02": "BR02", "NON_VAT": "BR02"}
    if raw not in mapping:
        raise ValidationError({"source_branch": "Use ALL, BR01, or BR02."})
    return mapping[raw]


def _sources(request):
    """Return physical report sources. BR03 is a view only; never query default transactions."""
    active = active_interface_branch(request)
    if not active:
        return []
    code = str(active.branch_code or "").upper()
    rows = _physical_rows()
    if code in PHYSICAL:
        branch = rows.get(code)
        return [(PHYSICAL[code], branch, code)] if branch else []
    if code == "BR03":
        requested = _requested_source(request)
        codes = [requested] if requested else ["BR01", "BR02"]
        return [
            (PHYSICAL[c], rows[c], c)
            for c in codes
            if c in rows
        ]
    return []


def _source_meta(branch, code, object_id=None):
    data = {
        "source_branch": code,
        "source_branch_code": code,
        "source_branch_id": branch.pk if branch else None,
        "source_branch_name": branch.branch_name if branch else code,
    }
    if object_id is not None:
        prefix = "VAT" if code == "BR01" else "NON_VAT"
        data["resource_key"] = f"{prefix}:{object_id}"
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_dashboard(request):
    from apps.inventory.models import ProductStock
    from apps.purchases.models import PurchaseOrder, SupplierBill
    from apps.sales.models import SalesInvoice

    today = timezone.localdate()
    month_start = today.replace(day=1)
    first_month = _shift_month(_month_start(today), -5)
    valuation_expression = ExpressionWrapper(
        F("current_stock") * F("average_unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=2),
    )

    totals = {"sales_month": ZERO, "purchases_month": ZERO, "receivables": ZERO, "payables": ZERO, "inventory_value": ZERO}
    sales_by_month, purchases_by_month, by_branch = {}, {}, []

    for alias, branch, code in _sources(request):
        invoices = SalesInvoice.objects.using(alias).filter(branch_id=branch.pk).exclude(payment_status="VOID")
        pos = PurchaseOrder.objects.using(alias).filter(branch_id=branch.pk).exclude(status="CANCELLED")
        bills = SupplierBill.objects.using(alias).filter(branch_id=branch.pk).exclude(status="CANCELLED")
        stocks = ProductStock.objects.using(alias).filter(branch_id=branch.pk)

        branch_values = {
            "sales_month": invoices.filter(invoice_date__gte=month_start).aggregate(total=Coalesce(Sum("total_amount"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2)))["total"] or ZERO,
            "purchases_month": pos.filter(order_date__gte=month_start).aggregate(total=Coalesce(Sum("total_amount"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2)))["total"] or ZERO,
            "receivables": invoices.filter(balance_due__gt=0).aggregate(total=Coalesce(Sum("balance_due"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2)))["total"] or ZERO,
            "payables": bills.filter(balance_due__gt=0).aggregate(total=Coalesce(Sum("balance_due"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2)))["total"] or ZERO,
            "inventory_value": stocks.aggregate(total=Coalesce(Sum(valuation_expression), ZERO, output_field=DecimalField(max_digits=20, decimal_places=2)))["total"] or ZERO,
        }
        for key, value in branch_values.items():
            totals[key] += value
        by_branch.append({**_source_meta(branch, code), **branch_values})

        for row in invoices.filter(invoice_date__gte=first_month).annotate(month=TruncMonth("invoice_date")).values("month").annotate(total=Coalesce(Sum("total_amount"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2))):
            month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            sales_by_month[month] = sales_by_month.get(month, ZERO) + (row["total"] or ZERO)
        for row in pos.filter(order_date__gte=first_month).annotate(month=TruncMonth("order_date")).values("month").annotate(total=Coalesce(Sum("total_amount"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2))):
            month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            purchases_by_month[month] = purchases_by_month.get(month, ZERO) + (row["total"] or ZERO)

    trend = []
    for offset in range(6):
        month = _shift_month(first_month, offset)
        trend.append({"month": f"{month_abbr[month.month]} {str(month.year)[-2:]}", "sales": sales_by_month.get(month, ZERO), "purchases": purchases_by_month.get(month, ZERO)})

    return ok({"kpi": totals, "trend": trend, "by_branch": by_branch}, message="Reports dashboard fetched successfully")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def purchase_report(request):
    from apps.purchases.models import PurchaseOrder, SupplierBill

    date_from, date_to = _date_param(request, "date_from"), _date_param(request, "date_to")
    status_value = request.query_params.get("status")
    rows, outstanding = [], ZERO

    for alias, branch, code in _sources(request):
        qs = PurchaseOrder.objects.using(alias).filter(branch_id=branch.pk).select_related("supplier", "branch").order_by("-order_date", "-id")
        qs = _apply_date_range(qs, "order_date", date_from, date_to)
        if status_value and status_value != "ALL":
            qs = qs.filter(status=status_value)
        bills = SupplierBill.objects.using(alias).filter(branch_id=branch.pk).exclude(status="CANCELLED")
        bills = _apply_date_range(bills, "bill_date", date_from, date_to)
        outstanding += bills.filter(balance_due__gt=0).aggregate(total=Coalesce(Sum("balance_due"), ZERO, output_field=DecimalField(max_digits=18, decimal_places=2)))["total"] or ZERO
        for order in qs:
            rows.append({"id": order.id, "po_number": order.po_number, "date": order.order_date, "supplier": order.supplier.supplier_name, "branch": branch.branch_name, "subtotal": order.subtotal, "vat_amount": order.vat_amount, "total": order.total_amount, "status": order.status, "payment_status": order.payment_status, **_source_meta(branch, code, order.id)})

    rows.sort(key=lambda row: (row.get("date"), row.get("id")), reverse=True)
    return ok({"summary": {"orders": len(rows), "purchase_value": sum((_decimal(r["total"]) for r in rows), ZERO), "approved_orders": sum(1 for r in rows if r["status"] in {"APPROVED", "PARTIALLY_RECEIVED", "RECEIVED"}), "outstanding_payables": outstanding}, "rows": rows}, message="Purchase report fetched successfully")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inventory_report(request):
    from apps.inventory.models import ProductStock

    rows, branch_totals = [], {}
    for alias, branch, code in _sources(request):
        qs = ProductStock.objects.using(alias).filter(branch_id=branch.pk).select_related("product", "variant", "branch").order_by("product__product_name", "id")
        for stock in qs:
            unit_cost = _decimal(stock.average_unit_cost)
            stock_value = _decimal(stock.current_stock) * unit_cost
            available = max(0, int(stock.current_stock or 0) - int(stock.reserved_stock or 0))
            rows.append({"id": stock.id, "branch": branch.branch_name, "product": stock.product.product_name, "variant": ", ".join(f"{k}: {v}" for k, v in (stock.variant.attributes or {}).items()) if stock.variant and not stock.variant.is_base else ("Base" if stock.variant else ""), "sku": getattr(stock.product, "sku", ""), "current_stock": stock.current_stock, "reserved_stock": stock.reserved_stock, "available_stock": available, "damaged_stock": stock.damaged_stock, "reorder_level": stock.reorder_level, "average_unit_cost": unit_cost, "value": stock_value, "low_stock": available <= int(stock.reorder_level or 0), **_source_meta(branch, code, stock.id)})
            branch_totals[code] = branch_totals.get(code, ZERO) + stock_value

    return ok({"summary": {"stock_lines": len(rows), "total_units": sum(int(r["current_stock"] or 0) for r in rows), "inventory_value": sum((_decimal(r["value"]) for r in rows), ZERO), "low_stock_items": sum(1 for r in rows if r["low_stock"])}, "valuation_by_branch": [{"source_branch": code, "branch": "Branch 1" if code == "BR01" else "Branch 2", "value": value} for code, value in sorted(branch_totals.items())], "rows": rows}, message="Inventory report fetched successfully")
