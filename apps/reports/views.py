from calendar import month_abbr
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError, PermissionDenied
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
    if str(active.branch_code or "").upper() == "CONSOLIDATED":
        return [("default", active, "CONSOLIDATED")]
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


def _can_report(user, *codes):
    """Permissions belong to the user; role permissions do not grant access."""
    return bool(getattr(user, "is_superuser", False) or any(
        user.has_operation_permission(code) for code in codes
    ))


def _require_report(user, code):
    if not _can_report(user, code):
        raise PermissionDenied("You do not have permission to view this report.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_dashboard(request):
    """Permission-scoped live operational overview across physical tenant schemas.

    The virtual branch owns no stock or financial transactions. Never query its
    default database for branch-owned objects or use the legacy vat/non_vat aliases.
    """
    import logging
    from django.db.models import Count, IntegerField, Q
    logger = logging.getLogger(__name__)
    from apps.branch_data.schema_routing import register_branch_connection
    from apps.branch_data.workforce_flow import (
        is_combined, is_physical, physical_branches, branch_from_value,
    )
    from apps.inventory.models import ProductStock, RackStockAllocation
    from apps.purchases.models import PurchaseOrder, SupplierBill
    from apps.sales.models import SalesInvoice
    from apps.hrms.models import Employee
    from apps.fleet.models import Vehicle

    user = request.user
    can_sales = _can_report(user, "reports.sales.view", "sales.invoices.view")
    can_purchase = _can_report(user, "reports.purchase.view", "purchase.purchase_orders.view")
    can_inventory = _can_report(user, "reports.inventory.view", "inventory.stock.view")
    can_receivables = _can_report(user, "reports.finance.view", "accounting.receivables.view")
    can_payables = _can_report(user, "reports.finance.view", "accounting.payables.view")
    can_finance = can_receivables or can_payables
    can_hrms = _can_report(user, "hrms.employees.view")
    can_fleet = _can_report(user, "fleet.vehicles.view")
    if not (can_sales or can_purchase or can_inventory or can_finance or can_hrms or can_fleet or _can_report(user, "reports.dashboard.view")):
        raise PermissionDenied("Dashboard access is not permitted.")

    active = active_interface_branch(request)
    if not active:
        raise ValidationError({"branch": "Select an active branch to load dashboard data."})
    if is_physical(active):
        branches = [active]
    elif is_combined(active):
        requested = request.query_params.get("source_branch")
        if requested and str(requested).upper() != "ALL":
            selected = branch_from_value(requested)
            if not is_physical(selected):
                raise ValidationError({"source_branch": "Select an active physical branch."})
            branches = [selected]
        else:
            branches = physical_branches()
    else:
        raise ValidationError({"branch": "Unsupported dashboard branch."})

    today = timezone.localdate()
    month_start = today.replace(day=1)
    first_month = _shift_month(month_start, -5)
    money = DecimalField(max_digits=20, decimal_places=2)
    zero_money = Decimal("0.00")
    money_sum = lambda qs, field: qs.aggregate(v=Coalesce(Sum(field), zero_money, output_field=money))["v"] or zero_money
    valuation_expression = ExpressionWrapper(
        F("current_stock") * F("average_unit_cost"), output_field=money
    )
    allowed = {
        "sales_month": can_sales,
        "purchases_month": can_purchase,
        "inventory_value": can_inventory,
        "receivables": can_receivables,
        "payables": can_payables,
        "stock_units": can_inventory,
        "low_stock_items": can_inventory,
        "unallocated_units": can_inventory,
        "open_purchase_orders": can_purchase,
        "open_sales_invoices": can_sales,
        "active_employees": can_hrms,
        "fleet_vehicles": can_fleet,
    }
    totals = {key: (0 if key in {"stock_units", "low_stock_items", "unallocated_units", "open_purchase_orders", "open_sales_invoices", "active_employees", "fleet_vehicles"} else zero_money) for key, enabled in allowed.items() if enabled}
    by_branch = []
    sales_by_month, purchases_by_month = {}, {}
    activity = []
    failed_metrics = set()
    warnings = []

    # Workforce and fleet live in the shared database, unlike sales/inventory.
    # Apply the same physical branch filter and never count virtual ownership.
    branch_ids = [branch.pk for branch in branches]
    if can_hrms:
        try:
            totals["active_employees"] = Employee.objects.using("default").filter(
                branch_id__in=branch_ids, status="ACTIVE"
            ).count()
        except Exception:
            logger.exception("Dashboard HRMS summary failed")
            failed_metrics.add("active_employees")
            warnings.append("HRMS metrics temporarily unavailable")
    if can_fleet:
        try:
            totals["fleet_vehicles"] = Vehicle.objects.using("default").filter(
                branch_id__in=branch_ids
            ).exclude(status="INACTIVE").count()
        except Exception:
            logger.exception("Dashboard fleet summary failed")
            failed_metrics.add("fleet_vehicles")
            warnings.append("Fleet metrics temporarily unavailable")

    for branch in branches:
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        row = {
            "source_branch": branch.branch_code,
            "source_branch_code": branch.branch_code,
            "source_branch_id": branch.pk,
            "source_branch_name": branch.branch_name,
            "tax_mode": branch.tax_mode,
        }
        if can_inventory:
            try:
                stocks = ProductStock.objects.using(alias).filter(branch_id=branch.pk)
                stock_rows = stocks.aggregate(
                    stock_units=Coalesce(Sum("current_stock"), 0, output_field=IntegerField()),
                    inventory_value=Coalesce(Sum(valuation_expression), zero_money, output_field=money),
                    low_stock_items=Count("id", filter=Q(current_stock__lte=F("reorder_level"), reorder_level__gt=0)),
                )
                # Sum only allocated quantities for these exact tenant stock rows.
                allocated = RackStockAllocation.objects.using(alias).filter(
                    stock__branch_id=branch.pk
                ).aggregate(v=Coalesce(Sum("quantity"), 0, output_field=IntegerField()))["v"] or 0
                row.update(stock_rows)
                row["unallocated_units"] = max(0, stock_rows["stock_units"] - allocated)
            except Exception:
                logger.exception("Dashboard can_inventory metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['inventory_value', 'stock_units', 'low_stock_items', 'unallocated_units'])
                warnings.append("Can Inventory metrics unavailable for a branch")
        if can_sales or can_receivables:
            try:
                invoices = SalesInvoice.objects.using(alias).filter(branch_id=branch.pk).exclude(payment_status="VOID")
                if can_sales:
                    row["sales_month"] = money_sum(invoices.filter(invoice_date__gte=month_start, invoice_date__lte=today), "total_amount")
                    row["open_sales_invoices"] = invoices.filter(balance_due__gt=0).count()
                    for invoice in invoices.order_by("-created_at")[:4]:
                        activity.append({"type": "sale", "label": f"Invoice {invoice.invoice_number}", "amount": invoice.total_amount, "at": invoice.created_at.isoformat(), "branch": branch.branch_code, "url": "/sales/invoices"})
                    monthly = invoices.filter(invoice_date__gte=first_month).annotate(month=TruncMonth("invoice_date")).values("month").annotate(total=Coalesce(Sum("total_amount"), zero_money, output_field=money))
                    for item in monthly:
                        if item["month"]:
                            m = item["month"].date() if hasattr(item["month"], "date") else item["month"]
                            sales_by_month[m] = sales_by_month.get(m, zero_money) + (item["total"] or zero_money)
                if can_receivables:
                    row["receivables"] = money_sum(invoices.filter(balance_due__gt=0), "balance_due")
            except Exception:
                logger.exception("Dashboard can_sales metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['sales_month', 'open_sales_invoices', 'receivables'])
                warnings.append("Can Sales metrics unavailable for a branch")
        if can_purchase:
            try:
                pos = PurchaseOrder.objects.using(alias).filter(branch_id=branch.pk).exclude(status="CANCELLED")
                row["purchases_month"] = money_sum(pos.filter(order_date__gte=month_start, order_date__lte=today), "total_amount")
                row["open_purchase_orders"] = pos.exclude(status="RECEIVED").count()
                for po in pos.order_by("-created_at")[:4]:
                    activity.append({"type": "purchase", "label": f"PO {po.po_number}", "amount": po.total_amount, "at": po.created_at.isoformat(), "branch": branch.branch_code, "url": "/purchases/purchase-orders"})
                monthly = pos.filter(order_date__gte=first_month).annotate(month=TruncMonth("order_date")).values("month").annotate(total=Coalesce(Sum("total_amount"), zero_money, output_field=money))
                for item in monthly:
                    if item["month"]:
                        m = item["month"].date() if hasattr(item["month"], "date") else item["month"]
                        purchases_by_month[m] = purchases_by_month.get(m, zero_money) + (item["total"] or zero_money)
            except Exception:
                logger.exception("Dashboard can_purchase metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['purchases_month', 'open_purchase_orders'])
                warnings.append("Can Purchase metrics unavailable for a branch")
        if can_payables:
            try:
                bills = SupplierBill.objects.using(alias).filter(branch_id=branch.pk).exclude(status="CANCELLED")
                row["payables"] = money_sum(bills.filter(balance_due__gt=0), "balance_due")
            except Exception:
                logger.exception("Dashboard can_payables metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['payables'])
                warnings.append("Can Payables metrics unavailable for a branch")
        if can_hrms:
            try:
                row["active_employees"] = Employee.objects.using("default").filter(branch_id=branch.pk, status="ACTIVE").count()
            except Exception:
                logger.exception("Dashboard can_hrms metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['active_employees'])
                warnings.append("Can Hrms metrics unavailable for a branch")
        if can_fleet:
            try:
                row["fleet_vehicles"] = Vehicle.objects.using("default").filter(branch_id=branch.pk).exclude(status="INACTIVE").count()
            except Exception:
                logger.exception("Dashboard can_fleet metric failed for branch %s", branch.branch_code)
                failed_metrics.update(['fleet_vehicles'])
                warnings.append("Can Fleet metrics unavailable for a branch")
        for key in totals:
            if key not in {"active_employees", "fleet_vehicles"}:
                totals[key] += row.get(key, 0)
        by_branch.append(row)

    for failed in failed_metrics:
        totals.pop(failed, None)
        for item in by_branch:
            item.pop(failed, None)
    if "sales_month" in failed_metrics:
        sales_by_month.clear()
    if "purchases_month" in failed_metrics:
        purchases_by_month.clear()
    trend = []
    for offset in range(6):
        month = _shift_month(first_month, offset)
        item = {"month": f"{month_abbr[month.month]} {str(month.year)[-2:]}"}
        if can_sales and "sales_month" not in failed_metrics:
            item["sales"] = sales_by_month.get(month, zero_money)
        if can_purchase and "purchases_month" not in failed_metrics:
            item["purchases"] = purchases_by_month.get(month, zero_money)
        trend.append(item)
    activity.sort(key=lambda row: row["at"], reverse=True)
    return ok({
        "kpi": totals,
        "trend": trend,
        "by_branch": by_branch,
        "recent_activity": activity[:12],
        "available_metrics": list(totals.keys()),
        "warnings": list(dict.fromkeys(warnings)),
        "scope": "consolidated" if is_combined(active) else "physical",
        "as_of": timezone.now().isoformat(),
    }, message="Dashboard fetched successfully")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def purchase_report(request):
    _require_report(request.user, "reports.purchase.view")
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
    _require_report(request.user, "reports.inventory.view")
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
