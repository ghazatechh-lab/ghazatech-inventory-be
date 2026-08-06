from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from .models import ServiceCharge, ServiceJob


class ServiceChargeSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = ServiceCharge
        fields = [
            "id",
            "charge_type",
            "description",
            "quantity",
            "unit_price",
            "line_total",
            "notes",
        ]


class ServiceJobSerializer(serializers.ModelSerializer):
    charges = ServiceChargeSerializer(many=True, required=False)
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    customer_display = serializers.SerializerMethodField()
    technician_name = serializers.SerializerMethodField()
    device_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    payment_status_display = serializers.CharField(
        source="get_payment_status_display",
        read_only=True,
    )
    parts_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ServiceJob
        fields = "__all__"
        read_only_fields = [
            "job_number",
            "completed_at",
            "delivered_at",
            "created_by",
            "updated_by",
        ]

    def get_customer_display(self, obj):
        if obj.customer:
            return (
                getattr(obj.customer, "customer_name", "")
                or getattr(obj.customer, "name", "")
                or obj.customer_name
            )
        return obj.customer_name

    def get_technician_name(self, obj):
        employee = obj.technician
        if not employee:
            return "Unassigned"
        full_name = " ".join(
            value for value in [employee.first_name, employee.last_name] if value
        ).strip()
        return full_name or employee.employee_code or f"Employee {employee.pk}"

    def get_device_name(self, obj):
        return " ".join(value for value in [obj.brand, obj.model] if value).strip()

    def validate(self, attrs):
        amount_paid = Decimal(str(attrs.get("amount_paid", getattr(self.instance, "amount_paid", 0)) or 0))
        labour = Decimal(str(attrs.get("labour_charge", getattr(self.instance, "labour_charge", 0)) or 0))
        discount = Decimal(str(attrs.get("discount_amount", getattr(self.instance, "discount_amount", 0)) or 0))
        tax = Decimal(str(attrs.get("tax_amount", getattr(self.instance, "tax_amount", 0)) or 0))
        if min(amount_paid, labour, discount, tax) < 0:
            raise serializers.ValidationError("Amounts cannot be negative.")
        return attrs

    def _save_charges(self, instance, charges):
        if charges is None:
            return
        instance.charges.all().delete()
        ServiceCharge.objects.bulk_create(
            [ServiceCharge(service_job=instance, **item) for item in charges]
        )

    @transaction.atomic
    def create(self, validated_data):
        charges = validated_data.pop("charges", [])
        instance = ServiceJob.objects.create(**validated_data)
        self._save_charges(instance, charges)
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        charges = validated_data.pop("charges", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        self._save_charges(instance, charges)
        return instance
