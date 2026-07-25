from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Shipment,
    ShipmentItem,
    ShipmentTrackingLog,
)


class ShipmentTrackingLogSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = ShipmentTrackingLog
        fields = "__all__"


class ShipmentItemSerializer(
    serializers.ModelSerializer,
):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )

    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )

    brand_name = serializers.CharField(
        source="product.brand.name",
        read_only=True,
        allow_null=True,
    )

    rack_code = serializers.CharField(
        source="rack.rack_code",
        read_only=True,
        allow_null=True,
    )

    total_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = ShipmentItem
        exclude = ["shipment"]

    def validate(self, attrs):
        received = attrs.get(
            "received_quantity",
            getattr(
                self.instance,
                "received_quantity",
                0,
            ),
        )

        accepted = attrs.get(
            "accepted_quantity",
            getattr(
                self.instance,
                "accepted_quantity",
                0,
            ),
        )

        rejected = attrs.get(
            "rejected_quantity",
            getattr(
                self.instance,
                "rejected_quantity",
                0,
            ),
        )

        if accepted + rejected != received:
            raise serializers.ValidationError(
                "Accepted plus rejected quantity must equal received quantity."
            )

        rack = attrs.get(
            "rack",
            getattr(
                self.instance,
                "rack",
                None,
            ),
        )

        shipment = self.context.get(
            "shipment",
        )

        if rack and shipment and rack.branch_id != shipment.branch_id:
            raise serializers.ValidationError(
                {"rack": "Rack must belong to the receiving branch."}
            )

        return attrs


class ShipmentSerializer(
    serializers.ModelSerializer,
):
    items = ShipmentItemSerializer(
        many=True,
        required=False,
    )

    tracking_logs = ShipmentTrackingLogSerializer(
        many=True,
        read_only=True,
    )

    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )

    po_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )

    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    total_received_quantity = serializers.SerializerMethodField()

    total_accepted_quantity = serializers.SerializerMethodField()

    total_rejected_quantity = serializers.SerializerMethodField()

    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = "__all__"

    def get_received_by_name(
        self,
        obj,
    ):
        if not obj.received_by:
            return ""

        if hasattr(
            obj.received_by,
            "get_full_name",
        ):
            full_name = (obj.received_by.get_full_name() or "").strip()

            if full_name:
                return full_name

        return (
            getattr(
                obj.received_by,
                "display_name",
                "",
            )
            or getattr(
                obj.received_by,
                "username",
                "",
            )
            or getattr(
                obj.received_by,
                "email",
                "",
            )
        )

    def get_total_received_quantity(
        self,
        obj,
    ):
        return sum(item.received_quantity for item in obj.items.all())

    def get_total_accepted_quantity(
        self,
        obj,
    ):
        return sum(item.accepted_quantity for item in obj.items.all())

    def get_total_rejected_quantity(
        self,
        obj,
    ):
        return sum(item.rejected_quantity for item in obj.items.all())

    def _generate_number(self):
        prefix = timezone.now().strftime(
            "SHP-%Y%m",
        )

        latest = (
            Shipment.objects.filter(
                shipment_number__startswith=prefix,
            )
            .order_by("-id")
            .first()
        )

        sequence = 1

        if latest:
            try:
                sequence = int(latest.shipment_number.split("-")[-1]) + 1
            except (
                TypeError,
                ValueError,
            ):
                sequence = (
                    Shipment.objects.filter(
                        shipment_number__startswith=prefix,
                    ).count()
                    + 1
                )

        return f"{prefix}-{sequence:04d}"

    def validate(self, attrs):
        purchase_order = attrs.get(
            "purchase_order",
            getattr(
                self.instance,
                "purchase_order",
                None,
            ),
        )

        supplier = attrs.get(
            "supplier",
            getattr(
                self.instance,
                "supplier",
                None,
            ),
        )

        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        if purchase_order:
            if supplier and purchase_order.supplier_id != supplier.id:
                raise serializers.ValidationError(
                    {"supplier": "Supplier must match the selected purchase order."}
                )

            if branch and purchase_order.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "branch": "Receiving branch must match the selected purchase order."
                    }
                )

        return attrs

    def _save_items(
        self,
        shipment,
        items,
    ):
        shipment.items.all().delete()

        for item in items:
            item.pop("id", None)

            serializer = ShipmentItemSerializer(
                data=item,
                context={
                    **self.context,
                    "shipment": shipment,
                },
            )

            serializer.is_valid(
                raise_exception=True,
            )

            ShipmentItem.objects.create(
                shipment=shipment,
                **serializer.validated_data,
            )

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            [],
        )

        if not items:
            raise serializers.ValidationError(
                {"items": "At least one shipment item is required."}
            )

        if not validated_data.get(
            "shipment_number",
        ):
            validated_data["shipment_number"] = self._generate_number()

        shipment = Shipment.objects.create(
            **validated_data,
        )

        self._save_items(
            shipment,
            items,
        )

        return shipment

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            None,
        )

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "At least one shipment item is required."}
                )

            self._save_items(
                instance,
                items,
            )

        return instance
