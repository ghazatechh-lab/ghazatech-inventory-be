from rest_framework import serializers
from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
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

    def create(self, validated_data):
        if not validated_data.get("customer_code"):
            last_customer = Customer.objects.order_by("-id").first()
            next_number = 1 if not last_customer else last_customer.id + 1
            validated_data["customer_code"] = f"CUS-{next_number:05d}"

        return super().create(validated_data)
