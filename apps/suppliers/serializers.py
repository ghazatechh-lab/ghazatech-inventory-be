from pathlib import Path

from django.db.models import Sum
from rest_framework import serializers

from .models import (
    Supplier,
    SupplierDocument,
)


class SupplierDocumentSerializer(
    serializers.ModelSerializer,
):
    file_url = serializers.SerializerMethodField()

    file_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierDocument

        fields = [
            "id",
            "file",
            "file_url",
            "file_name",
            "original_name",
            "file_size",
            "content_type",
            "uploaded_by",
            "created_at",
        ]

        read_only_fields = fields

    def get_file_url(self, obj):
        request = self.context.get(
            "request",
        )

        if not obj.file:
            return None

        url = obj.file.url

        return (
            request.build_absolute_uri(
                url,
            )
            if request
            else url
        )

    def get_file_name(self, obj):
        if not obj.file:
            return ""

        return Path(
            obj.file.name,
        ).name


class SupplierSerializer(
    serializers.ModelSerializer,
):
    total_purchases = serializers.SerializerMethodField()

    total_paid = serializers.SerializerMethodField()

    outstanding_balance = serializers.SerializerMethodField()

    credit_used_percent = serializers.SerializerMethodField()

    documents = SupplierDocumentSerializer(
        many=True,
        read_only=True,
    )

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

    def get_total_purchases(
        self,
        obj,
    ):
        return (
            obj.supplierbill_set.aggregate(
                value=Sum(
                    "total_amount",
                ),
            )["value"]
            or 0
        )

    def get_total_paid(
        self,
        obj,
    ):
        return (
            obj.supplierpayment_set.aggregate(
                value=Sum("amount"),
            )["value"]
            or 0
        )

    def get_outstanding_balance(
        self,
        obj,
    ):
        bills = (
            obj.supplierbill_set.aggregate(
                value=Sum(
                    "balance_due",
                ),
            )["value"]
            or 0
        )

        return bills + obj.opening_balance

    def get_credit_used_percent(
        self,
        obj,
    ):
        if not obj.credit_limit:
            return 0

        outstanding = float(
            self.get_outstanding_balance(
                obj,
            ),
        )

        credit_limit = float(
            obj.credit_limit,
        )

        return min(
            100,
            round(
                outstanding / credit_limit * 100,
                2,
            ),
        )
