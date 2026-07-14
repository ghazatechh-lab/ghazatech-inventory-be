from rest_framework import serializers
from .models import *


class QuotationItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationItem
        exclude = ["quotation"]


class QuotationSerializer(serializers.ModelSerializer):
    items = QuotationItemSerializer(many=True)

    class Meta:
        model = Quotation
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "created_by", "updated_by"]

    def create(self, v):
        items = v.pop("items", [])
        q = Quotation.objects.create(**v)
        QuotationItem.objects.bulk_create(
            [QuotationItem(quotation=q, **x) for x in items]
        )
        return q


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesInvoiceItem
        exclude = ["invoice"]


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True)

    class Meta:
        model = SalesInvoice
        fields = "__all__"
        read_only_fields = [
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "is_confirmed",
        ]

    def create(self, v):
        items = v.pop("items", [])
        o = SalesInvoice.objects.create(**v)
        SalesInvoiceItem.objects.bulk_create(
            [SalesInvoiceItem(invoice=o, **x) for x in items]
        )
        return o


class SalesCreditNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesCreditNote
        fields = "__all__"


class SalesPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesPayment
        fields = "__all__"
