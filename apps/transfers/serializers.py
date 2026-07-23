from django.utils import timezone
from rest_framework import serializers

from .models import StockTransfer, StockTransferItem


class ItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockTransferItem
        exclude = ["transfer"]


class TransferSerializer(serializers.ModelSerializer):
    items = ItemSerializer(many=True)
    from_branch_name = serializers.CharField(
        source="from_branch.branch_name", read_only=True
    )
    from_branch_code = serializers.CharField(
        source="from_branch.branch_code", read_only=True
    )
    to_branch_name = serializers.CharField(
        source="to_branch.branch_name", read_only=True
    )
    to_branch_code = serializers.CharField(
        source="to_branch.branch_code", read_only=True
    )
    requested_by_name = serializers.CharField(
        source="requested_by.full_name", read_only=True
    )

    class Meta:
        model = StockTransfer
        fields = "__all__"
        read_only_fields = [
            "transfer_number",
            "requested_by",
            "approved_by",
            "dispatched_by",
            "received_by",
            "dispatch_date",
            "received_date",
            "status",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if attrs.get("from_branch") == attrs.get("to_branch"):
            raise serializers.ValidationError(
                {
                    "to_branch": "Destination branch must be different from source branch."
                }
            )
        return attrs

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        request = self.context["request"]
        transfer = StockTransfer.objects.create(
            **validated_data,
            transfer_number=f"TR-{timezone.now():%Y%m%d%H%M%S%f}",
            requested_by=request.user,
            transfer_date=timezone.localdate(),
            status="REQUESTED",
        )
        StockTransferItem.objects.bulk_create(
            [StockTransferItem(transfer=transfer, **item) for item in items]
        )
        return transfer
