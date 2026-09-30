from decimal import Decimal

from django.apps import apps
from django.db.models import Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import BranchDatabaseProfile, MasterInventorySyncLog
from .serializers import BranchDatabaseProfileSerializer, MasterInventorySyncLogSerializer


class BranchDatabaseProfileViewSet(ReadOnlyModelViewSet):
    queryset = BranchDatabaseProfile.objects.select_related("branch").all()
    serializer_class = BranchDatabaseProfileSerializer


class MasterInventorySyncLogViewSet(ReadOnlyModelViewSet):
    queryset = MasterInventorySyncLog.objects.select_related(
        "source_branch", "master_branch", "product", "variant"
    ).all()
    serializer_class = MasterInventorySyncLogSerializer
    filterset_fields = ["source_branch", "master_branch", "status", "product"]
    search_fields = ["source_document_number", "product__product_name", "product__sku"]


def _sum_model(alias, app_label, model_name, field, branch_id=None):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return Decimal("0")
    qs = model.objects.using(alias).all()
    field_names = {f.name for f in model._meta.concrete_fields}
    if branch_id and "branch" in field_names:
        qs = qs.filter(branch_id=branch_id)
    if field not in field_names:
        return Decimal("0")
    return Decimal(qs.aggregate(value=Sum(field))["value"] or 0)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def combined_summary(request):
    """Master-branch snapshot from the physically separated databases."""
    profiles = {
        p.mode: p
        for p in BranchDatabaseProfile.objects.select_related("branch").filter(
            is_active=True
        )
    }
    master = profiles.get("MASTER")
    if not master:
        return Response({"detail": "Master branch is not configured."}, status=409)

    result = {}
    for mode in ("VAT", "NON_VAT"):
        profile = profiles.get(mode)
        if not profile:
            continue
        alias = profile.database_alias
        branch_id = profile.branch_id
        sales = _sum_model(alias, "sales", "SalesInvoice", "total_amount", branch_id)
        purchases = _sum_model(
            alias, "purchases", "PurchaseOrder", "total_amount", branch_id
        )
        supplier_payments = _sum_model(
            alias, "purchases", "SupplierPayment", "amount", branch_id
        )
        expenses = _sum_model(alias, "finance", "Expense", "amount", branch_id)
        result[mode.lower()] = {
            "branch": {"id": branch_id, "name": profile.branch.branch_name},
            "database": alias,
            "sales": str(sales),
            "purchases": str(purchases),
            "supplier_payments": str(supplier_payments),
            "expenses": str(expenses),
        }

    def total(key):
        return str(
            sum(
                (Decimal(v.get(key, "0")) for v in result.values()),
                Decimal("0"),
            )
        )

    return Response(
        {
            "master_branch": {
                "id": master.branch_id,
                "name": master.branch.branch_name,
            },
            "sources": result,
            "combined": {
                "sales": total("sales"),
                "purchases": total("purchases"),
                "supplier_payments": total("supplier_payments"),
                "expenses": total("expenses"),
            },
        }
    )
