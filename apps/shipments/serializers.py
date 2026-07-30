from decimal import Decimal

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


class ShipmentTrackingLogSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = ShipmentTrackingLog
        fields = "__all__"


class ShipmentItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    product_image = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    rack_code = serializers.CharField(
        source="rack.rack_code",
        read_only=True,
        allow_null=True,
    )
    rack_name = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()
    accepted_value = serializers.SerializerMethodField()
    rejected_value = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentItem
        exclude = ["shipment"]

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku
        return getattr(obj.product, "sku", "")

    def get_brand_name(self, obj):
        brand = getattr(obj.product, "brand", None)
        return getattr(brand, "name", None) or getattr(brand, "brand_name", None) or ""

    def get_product_image(self, obj):
        image = getattr(obj.product, "image", None) or getattr(
            obj.product, "product_image", None
        )
        if not image:
            return None
        try:
            url = image.url
        except (AttributeError, ValueError):
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""
        return (
            getattr(obj.variant, "display_name", None)
            or getattr(obj.variant, "variant_name", None)
            or str(obj.variant)
        )

    def get_rack_name(self, obj):
        if not obj.rack:
            return ""
        return (
            getattr(obj.rack, "rack_name", None)
            or getattr(obj.rack, "name", None)
            or ""
        )

    def get_total_cost(self, obj):
        return Decimal(str(obj.received_quantity or 0)) * Decimal(
            str(obj.unit_cost or 0)
        )

    def get_accepted_value(self, obj):
        return Decimal(str(obj.accepted_quantity or 0)) * Decimal(
            str(obj.unit_cost or 0)
        )

    def get_rejected_value(self, obj):
        return Decimal(str(obj.rejected_quantity or 0)) * Decimal(
            str(obj.unit_cost or 0)
        )

    def validate(self, attrs):
        received = Decimal(
            str(
                attrs.get(
                    "received_quantity",
                    getattr(self.instance, "received_quantity", 0),
                )
                or 0
            )
        )
        accepted = Decimal(
            str(
                attrs.get(
                    "accepted_quantity",
                    getattr(self.instance, "accepted_quantity", 0),
                )
                or 0
            )
        )
        rejected = Decimal(
            str(
                attrs.get(
                    "rejected_quantity",
                    getattr(self.instance, "rejected_quantity", 0),
                )
                or 0
            )
        )
        rack = attrs.get(
            "rack",
            getattr(self.instance, "rack", None),
        )
        shipment = self.context.get("shipment")
        purchase_order = getattr(shipment, "purchase_order", None)

        errors = {}

        if min(received, accepted, rejected) < 0:
            errors["received_quantity"] = (
                "Received, accepted, and rejected quantities cannot be negative."
            )

        if accepted + rejected != received:
            errors["accepted_quantity"] = (
                "Accepted plus rejected quantity must equal received quantity."
            )

        if rack and shipment and rack.branch_id != shipment.branch_id:
            errors["rack"] = "Rack must belong to the shipment branch."

        if errors:
            raise serializers.ValidationError(errors)

        # Any shipment linked to a supplier purchase order is an inbound
        # purchase shipment. Force the correct value so purchase receipts
        # cannot be stored as SALES and disappear from the purchase list.
        if purchase_order:
            attrs["shipment_type"] = "PURCHASE"

        return attrs


class ShipmentSerializer(serializers.ModelSerializer):
    # Generated by the backend during create. Declaring it read-only prevents
    # DRF from rejecting a new shipment before create() can assign the number.
    shipment_number = serializers.CharField(read_only=True)
    items = ShipmentItemSerializer(many=True)
    tracking_logs = ShipmentTrackingLogSerializer(
        many=True,
        read_only=True,
    )
    po_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
        allow_null=True,
    )
    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
        allow_null=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )
    received_by_name = serializers.SerializerMethodField()
    delivery_person_name = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )
    total_expected_quantity = serializers.SerializerMethodField()
    total_received_quantity = serializers.SerializerMethodField()
    total_accepted_quantity = serializers.SerializerMethodField()
    total_rejected_quantity = serializers.SerializerMethodField()
    total_shipment_value = serializers.SerializerMethodField()
    total_accepted_value = serializers.SerializerMethodField()
    total_rejected_value = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    shipment_type_display = serializers.CharField(
        source="get_shipment_type_display",
        read_only=True,
    )
    qc_status_display = serializers.CharField(
        source="get_qc_status_display",
        read_only=True,
    )

    class Meta:
        model = Shipment
        fields = "__all__"

    def _user_name(self, user):
        if not user:
            return ""
        if hasattr(user, "get_full_name"):
            name = (user.get_full_name() or "").strip()
            if name:
                return name
        return (
            getattr(user, "display_name", None)
            or getattr(user, "username", None)
            or getattr(user, "email", None)
            or str(user)
        )

    def get_received_by_name(self, obj):
        return self._user_name(obj.received_by)

    def get_delivery_person_name(self, obj):
        return self._user_name(obj.delivery_person)

    def _sum_quantity(self, obj, field):
        return sum(
            Decimal(str(getattr(item, field, 0) or 0)) for item in obj.items.all()
        )

    def _sum_value(self, obj, field):
        return sum(
            Decimal(str(getattr(item, field, 0) or 0))
            * Decimal(str(item.unit_cost or 0))
            for item in obj.items.all()
        )

    def get_total_expected_quantity(self, obj):
        return self._sum_quantity(obj, "expected_quantity")

    def get_total_received_quantity(self, obj):
        return self._sum_quantity(obj, "received_quantity")

    def get_total_accepted_quantity(self, obj):
        return self._sum_quantity(obj, "accepted_quantity")

    def get_total_rejected_quantity(self, obj):
        return self._sum_quantity(obj, "rejected_quantity")

    def get_total_shipment_value(self, obj):
        return self._sum_value(obj, "received_quantity")

    def get_total_accepted_value(self, obj):
        return self._sum_value(obj, "accepted_quantity")

    def get_total_rejected_value(self, obj):
        return self._sum_value(obj, "rejected_quantity")

    def _generate_number(self):
        prefix = timezone.now().strftime("SHP-%Y%m")
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
            except (TypeError, ValueError):
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
            getattr(self.instance, "purchase_order", None),
        )
        supplier = attrs.get(
            "supplier",
            getattr(self.instance, "supplier", None),
        )
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        errors = {}

        if purchase_order:
            if supplier and purchase_order.supplier_id != supplier.id:
                errors["supplier"] = "Supplier must match the selected purchase order."
            if branch and purchase_order.branch_id != branch.id:
                errors["branch"] = (
                    "Receiving branch must match the selected purchase order."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def _save_items(self, shipment, items):
        shipment.items.all().delete()

        for raw_item in items:
            item = dict(raw_item)
            item.pop("id", None)
            item.pop("shipment", None)

            ShipmentItem.objects.create(
                shipment=shipment,
                **item,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not items:
            raise serializers.ValidationError(
                {"items": ("At least one shipment item is required.")}
            )

        if not validated_data.get("shipment_number"):
            validated_data["shipment_number"] = self._generate_number()

        shipment = Shipment.objects.create(**validated_data)
        self._save_items(shipment, items)
        return shipment

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        instance = super().update(instance, validated_data)

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("At least one shipment item is required.")}
                )
            self._save_items(instance, items)

        return instance
