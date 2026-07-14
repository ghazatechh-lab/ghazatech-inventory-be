from rest_framework import serializers
from .models import *


class ShipmentTrackingLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentTrackingLog
        fields = "__all__"


class ShipmentSerializer(serializers.ModelSerializer):
    tracking_logs = ShipmentTrackingLogSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = "__all__"
