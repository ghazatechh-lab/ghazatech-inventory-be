from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    order_count = serializers.IntegerField(
        read_only=True,
        default=0,
    )

    last_order_date = serializers.DateField(
        read_only=True,
        allow_null=True,
    )

    balance_due = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
        default=0,
    )

    status = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = "__all__"

        read_only_fields = [
            "id",
            "customer_code",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "deleted_by",
        ]

    def get_status(self, obj):
        if not obj.is_active:
            return "INACTIVE"

        balance = getattr(obj, "balance_due", 0) or 0
        return "OUTSTANDING" if balance > 0 else "ACTIVE"

    def validate(self, attrs):
        customer_type = attrs.get(
            "customer_type",
            getattr(self.instance, "customer_type", "BUSINESS"),
        )

        if customer_type == "BUSINESS" and not attrs.get(
            "customer_name",
            getattr(self.instance, "customer_name", ""),
        ):
            raise serializers.ValidationError(
                {"customer_name": "Company name is required."}
            )

        return attrs

    def create(self, validated_data):
        if not validated_data.get("customer_code"):
            last_customer = Customer.objects.order_by("-id").first()
            next_number = 1 if not last_customer else last_customer.id + 1
            validated_data["customer_code"] = f"CUS-{next_number:05d}"

        if validated_data.get("trn") and not validated_data.get("trn_number"):
            validated_data["trn_number"] = validated_data["trn"]

        if validated_data.get("billing_address") and not validated_data.get("address"):
            validated_data["address"] = validated_data["billing_address"]

        return super().create(validated_data)
