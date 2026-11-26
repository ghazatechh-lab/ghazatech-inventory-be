from django.db import models, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status
from apps.audit_logs.viewsets import AuditedModelViewSet as ModelViewSet
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
        .prefetch_related("items")
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
                f"The transfer {action_name} must target a physical tenant branch."
            ),
        )

    def get_queryset(self):
        queryset = super().get_queryset()

        active_branch = self._active_branch()
        if active_branch and is_physical_branch(active_branch):
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

    @action(detail=False, methods=["get"], url_path="available-source-racks")
    def available_source_racks(self, request):
        """List only source-branch racks holding the selected product/variant.

        Query: from_branch=<branch ID>&product=<tenant product ID>&variant=<optional ID>.
        IDs are scoped to the source tenant, never the combined/default DB.
        ``max_transferable_quantity`` reflects the dispatch rule that a single
        warehouse stock row must fulfill the item.
        """
        from apps.branch_data.schema_routing import register_branch_connection
        from apps.inventory.models import (
            Product, ProductVariant, ProductStock, RackStockAllocation,
        )

        try:
            branch_id = int(request.query_params.get("from_branch"))
            product_id = int(request.query_params.get("product"))
            raw_variant = request.query_params.get("variant")
            variant_id = int(raw_variant) if raw_variant not in (None, "", "null") else None
            if branch_id < 1 or product_id < 1 or (variant_id is not None and variant_id < 1):
                raise ValueError
        except (TypeError, ValueError):
            raise serializers.ValidationError({
                "detail": "Valid from_branch and product IDs are required; variant is optional."
            })

        branch = Branch.objects.using("default").filter(
            pk=branch_id, is_active=True, tax_mode__in=["VAT", "NON_VAT"]
        ).first()
        if not branch:
            raise serializers.ValidationError({"from_branch": "Select an active physical source branch."})

        active_branch = request_active_branch(request)
        if active_branch and is_physical_branch(active_branch) and active_branch.pk != branch.pk:
            raise PermissionDenied("Switch to the source branch to view its available racks.")

        alias = register_branch_connection(branch.pk, branch.tax_mode)
        product = Product.objects.using(alias).filter(
            pk=product_id, branch_id=branch.pk, is_active=True, is_deleted=False
        ).first()
        if product is None:
            raise serializers.ValidationError({"product": "Product is not available in the source branch."})

        stock_variant_id = None
        if variant_id is not None:
            variant = ProductVariant.objects.using(alias).filter(
                pk=variant_id, product_id=product.pk, is_active=True
            ).first()
            if variant is None:
                raise serializers.ValidationError({"variant": "Variant does not belong to the selected product."})
            if not variant.is_base:
                stock_variant_id = variant.pk

        stocks = list(ProductStock.objects.using(alias).filter(
            branch_id=branch.pk, product_id=product.pk, variant_id=stock_variant_id
        ))
        if not stocks:
            return ok([], message="No stock available in source racks.")

        stock_by_id = {row.pk: row for row in stocks}
        allocations = RackStockAllocation.objects.using(alias).filter(
            stock_id__in=stock_by_id, quantity__gt=0,
            rack__branch_id=branch.pk, rack__is_active=True,
        ).select_related("rack")
        racks = {}
        for allocation in allocations:
            stock = stock_by_id[allocation.stock_id]
            # Dispatch only supports one stock/warehouse row per transfer item.
            transferable = min(int(allocation.quantity), max(0, int(stock.available_stock)))
            if transferable <= 0:
                continue
            rack = allocation.rack
            entry = racks.setdefault(rack.pk, {
                "id": rack.pk,
                "rack_id": rack.pk,
                "rack_code": rack.rack_code,
                "rack_name": rack.rack_name,
                "allocated_quantity": 0,
                "available_quantity": 0,
                "max_transferable_quantity": 0,
            })
            entry["allocated_quantity"] += int(allocation.quantity)
            entry["available_quantity"] += transferable
            entry["max_transferable_quantity"] = max(
                entry["max_transferable_quantity"], transferable
            )

        return ok(sorted(racks.values(), key=lambda r: (r["rack_code"], r["id"])))

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
        source_branch = self._require_physical_action_branch(transfer, action_name="dispatch")
        from apps.inventory.rack_ops import rack_for_branch
        from apps.branch_data.schema_routing import register_branch_connection
        from .models import StockTransferItem
        assignments = request.data.get('racks', {})
        if not isinstance(assignments, dict):
            raise serializers.ValidationError({'racks': 'Provide a rack selection for every item.'})
        alias = register_branch_connection(source_branch.pk, source_branch.tax_mode)
        items = list(StockTransferItem.objects.using('default').filter(transfer_id=transfer.pk))
        for item in items:
            choice = assignments.get(str(item.pk), item.source_rack_id)
            try:
                rack_id = int(choice)
            except (TypeError, ValueError):
                raise serializers.ValidationError({'racks': f'Select a source rack for item {item.pk}.'})
            rack_for_branch(alias, source_branch.pk, rack_id)
            if transfer.status == 'IN_TRANSIT' and item.source_rack_id != rack_id:
                raise serializers.ValidationError({'racks': 'Cannot change a source rack after dispatch.'})
            item.source_rack_id = rack_id
        with transaction.atomic(using='default'):
            StockTransferItem.objects.using('default').bulk_update(items, ['source_rack_id'])
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

        # The administrator can receive from Consolidated. All physical stock
        # mutations are explicitly directed to transfer.to_branch's tenant.
        if not is_admin_user(request.user):
            if not active_branch or not is_physical_branch(active_branch) or active_branch.pk != destination_branch.pk:
                raise PermissionDenied("Switch to the destination branch to receive this transfer.")
        from apps.inventory.rack_ops import rack_for_branch
        from apps.branch_data.schema_routing import register_branch_connection
        from .models import StockTransferItem
        assignments = request.data.get('racks')
        if not isinstance(assignments, dict):
            raise serializers.ValidationError({'racks': 'Choose a destination rack for each transfer item.'})
        alias = register_branch_connection(destination_branch.pk, destination_branch.tax_mode)
        items = list(StockTransferItem.objects.using('default').filter(transfer_id=transfer.pk))
        for item in items:
            try:
                rack_id = int(assignments.get(str(item.pk)))
            except (TypeError, ValueError):
                raise serializers.ValidationError({'racks': f'Select a destination rack for item {item.pk}.'})
            rack_for_branch(alias, destination_branch.pk, rack_id)
            if item.destination_rack_id and item.destination_rack_id != rack_id:
                raise serializers.ValidationError({'racks': 'Destination rack cannot change after receiving has started.'})
            item.destination_rack_id = rack_id
        with transaction.atomic(using='default'):
            StockTransferItem.objects.using('default').bulk_update(items, ['destination_rack_id'])
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
