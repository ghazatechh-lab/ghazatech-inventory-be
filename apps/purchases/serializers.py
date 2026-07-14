from rest_framework import serializers
from .models import *


class POItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderItem
        exclude = ["purchase_order"]


class POSerializer(serializers.ModelSerializer):
    items = POItemSerializer(many=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"

    def create(self, v):
        items = v.pop("items", [])
        o = PurchaseOrder.objects.create(**v)
        PurchaseOrderItem.objects.bulk_create(
            [PurchaseOrderItem(purchase_order=o, **x) for x in items]
        )
        return o


class GRNItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceivedItem
        exclude = ["grn"]


class GRNSerializer(serializers.ModelSerializer):
    items = GRNItemSerializer(many=True)

    class Meta:
        model = GoodsReceivedNote
        fields = "__all__"

    def create(self, v):
        items = v.pop("items", [])
        o = GoodsReceivedNote.objects.create(**v)
        GoodsReceivedItem.objects.bulk_create(
            [GoodsReceivedItem(grn=o, **x) for x in items]
        )
        return o


class SupplierBillSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierBill
        fields = "__all__"


class SupplierPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPayment
        fields = "__all__"


class SupplierReturnSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierReturn
        fields = "__all__"
