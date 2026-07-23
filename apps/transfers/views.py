from django.db import models

from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet

from apps.common.response import ok
from .models import StockTransfer
from .serializers import TransferSerializer
from .services import dispatch as dispatch_transfer_service, receive


class StockTransferViewSet(ModelViewSet):
    queryset = (
        StockTransfer.objects.select_related(
            "from_branch",
            "to_branch",
            "requested_by",
            "approved_by",
            "dispatched_by",
            "received_by",
        )
        .prefetch_related("items__product")
        .all()
    )

    serializer_class = TransferSerializer

    filterset_fields = [
        "from_branch",
        "to_branch",
        "status",
    ]

    ordering_fields = [
        "transfer_number",
        "created_at",
        "transfer_date",
        "dispatch_date",
        "received_date",
        "status",
        "from_branch__branch_name",
        "to_branch__branch_name",
    ]

    search_fields = [
        "transfer_number",
        "from_branch__branch_name",
        "to_branch__branch_name",
        "status",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        q = self.request.query_params.get("q")
        if q:
            queryset = queryset.filter(
                models.Q(transfer_number__icontains=q)
                | models.Q(from_branch__branch_name__icontains=q)
                | models.Q(to_branch__branch_name__icontains=q)
                | models.Q(status__icontains=q)
            )

        return queryset

    @action(detail=True, methods=["post"], url_path="approve")
    def approve_transfer(self, request, pk=None):
        transfer = self.get_object()
        transfer.status = "APPROVED"
        transfer.approved_by = request.user
        transfer.save()

        return ok(
            TransferSerializer(transfer).data, message="Transfer approved successfully"
        )

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request, pk=None):
        transfer = dispatch_transfer_service(self.get_object(), request.user)

        return ok(
            TransferSerializer(transfer).data,
            message="Transfer dispatched successfully",
        )

    @action(detail=True, methods=["post"], url_path="receive")
    def receive_transfer(self, request, pk=None):
        transfer = receive(self.get_object(), request.user)

        return ok(
            TransferSerializer(transfer).data, message="Transfer received successfully"
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_transfer(self, request, pk=None):
        transfer = self.get_object()
        transfer.status = "CANCELLED"
        transfer.save()

        return ok(
            TransferSerializer(transfer).data, message="Transfer cancelled successfully"
        )
