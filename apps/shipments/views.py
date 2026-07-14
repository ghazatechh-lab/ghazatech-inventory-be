from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from .models import *
from .serializers import *
from apps.common.response import ok


class ShipmentViewSet(ModelViewSet):
    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    filterset_fields = ["branch", "customer", "status"]

    @action(detail=True, methods=["post"], url_path="update-status")
    def update_status(self, r, pk=None):
        o = self.get_object()
        o.status = r.data.get("status", o.status)
        o.save()
        ShipmentTrackingLog.objects.create(
            shipment=o,
            status=o.status,
            location=r.data.get("location", ""),
            remarks=r.data.get("remarks", ""),
            updated_by=r.user,
        )
        return ok(ShipmentSerializer(o).data)

    @action(detail=True, methods=["get"])
    def tracking(self, r, pk=None):
        return ok(
            ShipmentTrackingLogSerializer(
                self.get_object().tracking_logs.all(), many=True
            ).data
        )
