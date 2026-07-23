from django.db import transaction
from rest_framework import serializers
from .models import Shipment, ShipmentItem, ShipmentTrackingLog


class ShipmentTrackingLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentTrackingLog
        fields = "__all__"


class ShipmentItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = ShipmentItem
        exclude = ["shipment"]


class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, required=False)
    tracking_logs = ShipmentTrackingLogSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Shipment
        fields = "__all__"
        read_only_fields = ["received_by"]

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        obj = Shipment.objects.create(**validated_data)
        for item in items:
            ShipmentItem.objects.create(shipment=obj, **item)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            instance.items.all().delete()
            for item in items:
                ShipmentItem.objects.create(shipment=instance, **item)
        return instance
