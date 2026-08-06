from pathlib import Path

from django.db import transaction
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
            "supplier_code",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "deleted_by",
        ]

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        if not branch:
            raise serializers.ValidationError(
                {"branch": "Branch is required for a supplier."}
            )

        attrs["payment_terms_days"] = int(
            attrs.get(
                "payment_terms_days",
                getattr(self.instance, "payment_terms_days", 0),
            )
            or 0
        )

        return attrs

    def _generate_supplier_code(self, branch):
        branch_code = (
            str(getattr(branch, "branch_code", "") or f"B{branch.pk}")
            .strip()
            .upper()
            .replace(" ", "")
        )

        prefix = f"SUP-{branch_code}-"

        latest = (
            Supplier.objects.select_for_update()
            .filter(
                branch=branch,
                supplier_code__startswith=prefix,
            )
            .order_by("-supplier_code")
            .values_list("supplier_code", flat=True)
            .first()
        )

        sequence = 1

        if latest:
            try:
                sequence = int(latest.rsplit("-", 1)[-1]) + 1
            except (TypeError, ValueError):
                sequence = (
                    Supplier.objects.filter(
                        branch=branch,
                        supplier_code__startswith=prefix,
                    ).count()
                    + 1
                )

        candidate = f"{prefix}{sequence:04d}"

        while Supplier.objects.filter(supplier_code=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"

        return candidate

    @transaction.atomic
    def create(self, validated_data):
        branch = validated_data["branch"]
        validated_data.pop("supplier_code", None)
        validated_data["supplier_code"] = self._generate_supplier_code(branch)
        validated_data.setdefault("payment_terms_days", 0)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("supplier_code", None)
        return super().update(instance, validated_data)

    def get_total_purchases(
        self,
        obj,
    ):
        return (
            obj.supplier_bills.aggregate(
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
            obj.supplier_payments.aggregate(
                value=Sum("amount"),
            )["value"]
            or 0
        )

    def get_outstanding_balance(
        self,
        obj,
    ):
        bills = (
            obj.supplier_bills.aggregate(
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
