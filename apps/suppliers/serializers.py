from django.db.models import Sum
from rest_framework import serializers
from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    total_purchases = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    credit_used_percent = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = "__all__"
        read_only_fields = [
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "deleted_by",
        ]

    def get_total_purchases(self, obj):
        return obj.supplierbill_set.aggregate(v=Sum("total_amount"))["v"] or 0

    def get_total_paid(self, obj):
        return obj.supplierpayment_set.aggregate(v=Sum("amount"))["v"] or 0

    def get_outstanding_balance(self, obj):
        bills = obj.supplierbill_set.aggregate(v=Sum("balance_due"))["v"] or 0
        return bills + obj.opening_balance

    def get_credit_used_percent(self, obj):
        if not obj.credit_limit:
            return 0
        return min(
            100,
            round(
                float(self.get_outstanding_balance(obj))
                / float(obj.credit_limit)
                * 100,
                2,
            ),
        )
