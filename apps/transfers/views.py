from django.db import models
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ModelViewSet

from apps.common.response import ok
from apps.branches.models import Branch
from apps.branch_data.combined_views import DefaultCombinedBranchRequestMixin
from apps.branch_data.physical import (
    is_physical_branch,
    request_active_branch,
    require_physical_branch,
)
from .models import StockTransfer
from .serializers import TransferSerializer, is_admin_user
from .services import dispatch as dispatch_transfer_service, receive


class StockTransferViewSet(DefaultCombinedBranchRequestMixin, ModelViewSet):
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

    def _active_branch(self):
        """Return the branch currently selected in the UI/header."""
        branch_value = (
            self.request.query_params.get("branch")
            or self.request.headers.get("X-Branch-ID")
            or self.request.headers.get("X-Branch-Id")
        )
        if not branch_value:
            return None
        try:
            return Branch.objects.get(pk=int(branch_value))
        except (Branch.DoesNotExist, TypeError, ValueError):
            return None

    def _require_physical_action_branch(self, transfer, *, action_name):
        """Resolve stock-changing actions from the transfer itself.

        The transfer already stores its physical source and destination. Action
        requests must not depend on the global branch header being present.
        """
        branch = transfer.from_branch if action_name == "dispatch" else transfer.to_branch
        return require_physical_branch(
            branch,
            field=("from_branch" if action_name == "dispatch" else "to_branch"),
            message=(
                f"The transfer {action_name} branch must be Branch 1 or Branch 2. "
                "Branch 3 cannot own or move physical stock."
            ),
        )

    def get_queryset(self):
        queryset = super().get_queryset()

        active_branch = self._active_branch()
        if active_branch and active_branch.branch_code != "BR03":
            # Source branch owns the transfer from creation through dispatch and
            # keeps it in history afterwards. The destination branch receives
            # visibility only once goods have actually left the source branch.
            queryset = queryset.filter(
                models.Q(from_branch_id=active_branch.id)
                | (
                    models.Q(to_branch_id=active_branch.id)
                    & models.Q(status__in=["IN_TRANSIT", "DISPATCHED", "RECEIVED"])
                )
            )

        q = self.request.query_params.get("q") or self.request.query_params.get(
            "search"
        )
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
        require_physical_branch(transfer.from_branch, field="from_branch")
        require_physical_branch(transfer.to_branch, field="to_branch")
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
        transfer = self.get_object()
        self._require_physical_action_branch(transfer, action_name="dispatch")
        transfer = dispatch_transfer_service(transfer, request.user)
        return ok(
            TransferSerializer(transfer, context={"request": request}).data,
            message="Transfer dispatched successfully",
        )

    @action(detail=True, methods=["post"], url_path="receive")
    def receive_transfer(self, request, pk=None):
        transfer = self.get_object()

        destination_branch = self._require_physical_action_branch(
            transfer,
            action_name="receive",
        )
        active_branch = request_active_branch(request)

        # Receiving is intentionally stricter than viewing the transfer.
        # The stock-in operation must be performed while operating in the
        # actual physical destination branch. Source branch and BR03 may view
        # the transfer, but they cannot receive it.
        if not active_branch or not is_physical_branch(active_branch):
            raise PermissionDenied(
                "Switch to the destination physical branch before receiving this transfer."
            )

        active_code = str(active_branch.branch_code or "").upper()
        destination_code = str(destination_branch.branch_code or "").upper()

        # Compare canonical physical branch identity.  Branch codes are stable
        # across the multi-database setup, while mirrored database rows/object
        # instances must never be compared directly.
        same_destination = (
            active_code == destination_code
            and active_code in {"BR01", "BR02"}
        )

        if not same_destination:
            raise PermissionDenied(
                f"Only {destination_branch.branch_code} - "
                f"{destination_branch.branch_name} can receive this transfer."
            )

        transfer = receive(transfer, request.user)
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
