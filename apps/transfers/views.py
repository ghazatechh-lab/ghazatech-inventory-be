from django.db import models
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ModelViewSet

from apps.common.response import ok
from .models import StockTransfer
from .serializers import TransferSerializer, is_admin_user
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
        .prefetch_related(
            "items__product",
            "items__variant",
        )
        .all()
    )

    serializer_class = TransferSerializer

    filterset_fields = ["from_branch", "to_branch", "status"]

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
        "requested_by__full_name",
        "requested_by__email",
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
                | models.Q(requested_by__full_name__icontains=q)
                | models.Q(requested_by__email__icontains=q)
                | models.Q(status__icontains=q)
            )

        return queryset

    def destroy(self, request, *args, **kwargs):
        if not is_admin_user(request.user):
            raise PermissionDenied("Only an Admin can delete stock transfers.")

        transfer = self.get_object()
        current_status = str(transfer.status or "").upper()
        if current_status not in {"DRAFT", "REQUESTED", "APPROVED", "CANCELLED"}:
            raise serializers.ValidationError(
                {
                    "status": (
                        "A transfer cannot be deleted after it has been dispatched. "
                        "Cancel it before dispatch or keep it for stock history."
                    )
                }
            )

        transfer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve_transfer(self, request, pk=None):
        if not is_admin_user(request.user):
            raise PermissionDenied("Only an Admin can approve transfer requests.")

        transfer = self.get_object()
        current_status = str(transfer.status or "").upper()

        if current_status == "APPROVED":
            return ok(
                TransferSerializer(transfer, context={"request": request}).data,
                message="Transfer is already approved",
            )

        if current_status != "REQUESTED":
            raise serializers.ValidationError(
                {"status": "Only requested transfers can be approved."}
            )

        transfer.status = "APPROVED"
        transfer.approved_by = request.user
        transfer.approved_at = timezone.now()
        transfer.save(
            update_fields=["status", "approved_by", "approved_at", "updated_at"]
        )

        return ok(
            TransferSerializer(transfer, context={"request": request}).data,
            message="Transfer approved successfully",
        )

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request, pk=None):
        transfer = dispatch_transfer_service(self.get_object(), request.user)
        return ok(
            TransferSerializer(transfer, context={"request": request}).data,
            message="Transfer dispatched successfully",
        )

    @action(detail=True, methods=["post"], url_path="receive")
    def receive_transfer(self, request, pk=None):
        transfer = receive(self.get_object(), request.user)
        return ok(
            TransferSerializer(transfer, context={"request": request}).data,
            message="Transfer received successfully",
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_transfer(self, request, pk=None):
        transfer = self.get_object()
        current_status = str(transfer.status or "").upper()
        if current_status in {"IN_TRANSIT", "DISPATCHED", "RECEIVED"}:
            raise serializers.ValidationError(
                {
                    "status": "Dispatched or received transfers cannot be cancelled without a stock reversal."
                }
            )
        transfer.status = "CANCELLED"
        transfer.cancelled_at = timezone.now()
        transfer.save(update_fields=["status", "cancelled_at", "updated_at"])

        return ok(
            TransferSerializer(transfer, context={"request": request}).data,
            message="Transfer cancelled successfully",
        )
