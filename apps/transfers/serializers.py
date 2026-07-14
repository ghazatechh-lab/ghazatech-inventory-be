from rest_framework import serializers
from .models import *


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransferItem
        exclude = ["transfer"]


class TransferSerializer(serializers.ModelSerializer):
    items = ItemSerializer(many=True)

    class Meta:
        model = StockTransfer
        fields = "__all__"

    def create(self, v):
        items = v.pop("items", [])
        o = StockTransfer.objects.create(**v)
        StockTransferItem.objects.bulk_create(
            [StockTransferItem(transfer=o, **x) for x in items]
        )
        return o
