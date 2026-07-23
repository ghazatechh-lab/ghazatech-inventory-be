from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet
from .models import Shipment, ShipmentTrackingLog
from .serializers import ShipmentSerializer, ShipmentTrackingLogSerializer
from apps.common.response import ok


class ShipmentViewSet(ModelViewSet):
    queryset = Shipment.objects.select_related(
        "purchase_order", "supplier", "branch", "invoice", "customer"
    ).prefetch_related("items__product", "tracking_logs")
    serializer_class = ShipmentSerializer
    filterset_fields = [
        "shipment_type",
        "branch",
        "supplier",
        "purchase_order",
        "customer",
        "status",
    ]
    search_fields = [
        "shipment_number",
        "tracking_number",
        "courier",
        "supplier__supplier_name",
        "purchase_order__po_number",
    ]
    ordering_fields = [
        "shipment_number",
        "shipment_date",
        "expected_date",
        "received_date",
        "status",
        "created_at",
    ]
    ordering = ["-shipment_date", "-id"]

    def perform_create(self, serializer):
        kwargs = {}
        if serializer.validated_data.get("status") in ["RECEIVED", "COMPLETED"]:
            kwargs["received_by"] = self.request.user
        serializer.save(**kwargs)

    @action(detail=True, methods=["post"], url_path="update-status")
    def update_status(self, request, pk=None):
        obj = self.get_object()
        obj.status = request.data.get("status", obj.status)
        if obj.status in ["RECEIVED", "COMPLETED"]:
            obj.received_by = request.user
        obj.save()
        ShipmentTrackingLog.objects.create(
            shipment=obj,
            status=obj.status,
            location=request.data.get("location", ""),
            remarks=request.data.get("remarks", ""),
            updated_by=request.user,
        )
        return ok(ShipmentSerializer(obj).data)

    @action(detail=True, methods=["get"])
    def tracking(self, request, pk=None):
        return ok(
            ShipmentTrackingLogSerializer(
                self.get_object().tracking_logs.all(), many=True
            ).data
        )
