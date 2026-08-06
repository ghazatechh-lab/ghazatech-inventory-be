from pathlib import Path

from django.db.models import Sum
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.parsers import (
    FormParser,
    JSONParser,
    MultiPartParser,
)
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import (
    Supplier,
    SupplierDocument,
)

import logging


from .serializers import (
    SupplierSerializer,
)

ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".doc",
    ".docx",
}

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024


class SupplierViewSet(
    ModelViewSet,
):
    queryset = Supplier.objects.filter(
        is_deleted=False,
    ).prefetch_related(
        "documents",
    )

    serializer_class = SupplierSerializer

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    search_fields = [
        "supplier_code",
        "supplier_name",
        "trade_name",
        "contact_person",
        "phone",
        "email",
        "trn_number",
        "branch__branch_name",
        "branch__branch_code",
    ]

    filterset_fields = [
        "branch",
        "is_active",
        "supplier_category",
        "currency",
    ]

    ordering_fields = [
        "supplier_name",
        "created_at",
        "credit_limit",
        "opening_balance",
        "is_active",
    ]

    ordering = [
        "supplier_name",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_id = self.request.query_params.get("branch")

        if branch_id not in (None, "", "all"):
            queryset = queryset.filter(branch_id=branch_id)

        return queryset

    def _validate_documents(
        self,
        files,
    ):
        errors = []

        for uploaded_file in files:
            extension = Path(
                uploaded_file.name,
            ).suffix.lower()

            if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
                errors.append(f"{uploaded_file.name}: unsupported file type.")

            if uploaded_file.size > MAX_DOCUMENT_SIZE:
                errors.append(f"{uploaded_file.name}: file exceeds 10 MB.")

        if errors:
            raise serializers.ValidationError(
                {
                    "documents": errors,
                }
            )

    def _save_documents(
        self,
        supplier,
    ):
        files = self.request.FILES.getlist(
            "documents",
        )

        if not files:
            return

        self._validate_documents(
            files,
        )

        for uploaded_file in files:
            SupplierDocument.objects.create(
                supplier=supplier,
                file=uploaded_file,
                original_name=uploaded_file.name,
                file_size=uploaded_file.size,
                content_type=uploaded_file.content_type or "",
                uploaded_by=(
                    self.request.user if self.request.user.is_authenticated else None
                ),
            )

    def perform_create(
        self,
        serializer,
    ):
        supplier = serializer.save()

        self._save_documents(
            supplier,
        )

    def perform_update(
        self,
        serializer,
    ):
        supplier = serializer.save()

        self._save_documents(
            supplier,
        )

    def perform_destroy(
        self,
        obj,
    ):
        obj.is_deleted = True
        obj.deleted_by = self.request.user

        obj.save(
            update_fields=[
                "is_deleted",
                "deleted_by",
                "updated_at",
            ],
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(
        self,
        request,
    ):
        queryset = self.filter_queryset(
            self.get_queryset(),
        )

        active = queryset.filter(
            is_active=True,
        ).count()

        total_credit = (
            queryset.aggregate(
                value=Sum(
                    "credit_limit",
                ),
            )["value"]
            or 0
        )

        opening_balance = (
            queryset.aggregate(
                value=Sum(
                    "opening_balance",
                ),
            )["value"]
            or 0
        )

        serializer = SupplierSerializer(
            queryset,
            many=True,
            context={
                "request": request,
            },
        )

        outstanding = sum(
            (item["outstanding_balance"] for item in serializer.data),
            0,
        )

        return Response(
            {
                "count": queryset.count(),
                "active": active,
                "credit_limit": total_credit,
                "opening_balance": opening_balance,
                "outstanding": outstanding,
            }
        )
