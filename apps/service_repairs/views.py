from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import ServiceJob
from .serializers import ServiceJobSerializer


ACTIVE_STATUSES = [
    ServiceJob.STATUS_RECEIVED,
    ServiceJob.STATUS_DIAGNOSING,
    ServiceJob.STATUS_AWAITING_APPROVAL,
    ServiceJob.STATUS_REPAIRING,
    ServiceJob.STATUS_READY,
]
HISTORY_STATUSES = [
    ServiceJob.STATUS_COMPLETED,
    ServiceJob.STATUS_DELIVERED,
    ServiceJob.STATUS_CANCELLED,
]


class ServiceJobViewSet(ModelViewSet):
    serializer_class = ServiceJobSerializer
    filterset_fields = [
        "branch",
        "status",
        "technician",
        "priority",
        "payment_status",
        "brand",
    ]
    search_fields = [
        "job_number",
        "customer_name",
        "phone",
        "email",
        "brand",
        "model",
        "serial_number",
        "complaint",
        "diagnosis",
    ]
    ordering_fields = [
        "job_number",
        "created_at",
        "expected_completion_date",
        "completed_at",
        "status",
        "priority",
    ]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        queryset = ServiceJob.objects.select_related(
            "branch",
            "customer",
            "technician",
        ).prefetch_related("charges")

        branch = self.request.query_params.get("branch")
        if branch not in (None, "", "all"):
            queryset = queryset.filter(branch_id=branch)

        section = self.request.query_params.get("section")
        if section == "active":
            queryset = queryset.filter(status__in=ACTIVE_STATUSES)
        elif section == "history":
            queryset = queryset.filter(status__in=HISTORY_STATUSES)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        queryset = self.get_queryset()
        all_for_branch = queryset
        if request.query_params.get("section"):
            all_for_branch = ServiceJob.objects.all()
            branch = request.query_params.get("branch")
            if branch not in (None, "", "all"):
                all_for_branch = all_for_branch.filter(branch_id=branch)

        data = all_for_branch.aggregate(
            total=Count("id"),
            open_jobs=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
            awaiting_approval=Count(
                "id", filter=Q(status=ServiceJob.STATUS_AWAITING_APPROVAL)
            ),
            ready=Count("id", filter=Q(status=ServiceJob.STATUS_READY)),
            completed=Count("id", filter=Q(status__in=HISTORY_STATUSES)),
            revenue=Coalesce(
                Sum("amount_paid", filter=Q(status__in=HISTORY_STATUSES)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        return Response(data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        job = self.get_object()
        serializer = self.get_serializer(
            job,
            data={
                "status": request.data.get("status", ServiceJob.STATUS_COMPLETED),
                "technician_notes": request.data.get(
                    "technician_notes", job.technician_notes
                ),
                "amount_paid": request.data.get("amount_paid", job.amount_paid),
                "payment_status": request.data.get(
                    "payment_status", job.payment_status
                ),
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
