from django.db.models import Sum
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(ModelViewSet):
    queryset = Supplier.objects.filter(is_deleted=False)
    serializer_class = SupplierSerializer
    search_fields = [
        "supplier_code",
        "supplier_name",
        "trade_name",
        "contact_person",
        "phone",
        "email",
        "trn_number",
    ]
    filterset_fields = ["is_active", "supplier_category", "currency"]
    ordering_fields = [
        "supplier_name",
        "created_at",
        "credit_limit",
        "opening_balance",
        "is_active",
    ]
    ordering = ["supplier_name"]

    def perform_destroy(self, obj):
        obj.is_deleted = True
        obj.deleted_by = self.request.user
        obj.save(update_fields=["is_deleted", "deleted_by", "updated_at"])

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        active = qs.filter(is_active=True).count()
        total_credit = qs.aggregate(v=Sum("credit_limit"))["v"] or 0
        opening = qs.aggregate(v=Sum("opening_balance"))["v"] or 0
        outstanding = sum(
            (s.outstanding_balance for s in SupplierSerializer(qs, many=True).data), 0
        )
        return Response(
            {
                "count": qs.count(),
                "active": active,
                "credit_limit": total_credit,
                "opening_balance": opening,
                "outstanding": outstanding,
            }
        )
