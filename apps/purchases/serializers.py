from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from .models import *


class POItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = PurchaseOrderItem
        exclude = ["purchase_order"]


class POSerializer(serializers.ModelSerializer):
    items = POItemSerializer(many=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by", "approved_by"]

    def _totals(self, items, data):
        subtotal = sum(
            (
                Decimal(str(x.get("quantity", 0)))
                * Decimal(str(x.get("unit_price", 0)))
                - Decimal(str(x.get("discount_amount", 0)))
                for x in items
            ),
            Decimal("0"),
        )
        vat = sum((Decimal(str(x.get("vat_amount", 0))) for x in items), Decimal("0"))
        shipping = Decimal(str(data.get("shipping_amount", 0)))
        discount = Decimal(str(data.get("discount_amount", 0)))
        return subtotal, vat, subtotal - discount + vat + shipping

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        subtotal, vat, total = self._totals(items, validated_data)
        validated_data.update(subtotal=subtotal, vat_amount=vat, total_amount=total)
        po = PurchaseOrder.objects.create(**validated_data)
        for item in items:
            line_total = (
                Decimal(str(item["quantity"])) * Decimal(str(item["unit_price"]))
                - Decimal(str(item.get("discount_amount", 0)))
                + Decimal(str(item.get("vat_amount", 0)))
            )
            PurchaseOrderItem.objects.create(
                purchase_order=po, line_total=line_total, **item
            )
        return po


class GRNItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = GoodsReceivedItem
        exclude = ["grn"]


class GRNSerializer(serializers.ModelSerializer):
    items = GRNItemSerializer(many=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)

    class Meta:
        model = GoodsReceivedNote
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by", "received_by"]

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        grn = GoodsReceivedNote.objects.create(**validated_data)
        for item in items:
            accepted = item.get("accepted_quantity")
            if accepted is None:
                accepted = max(
                    0,
                    item.get("received_quantity", 0) - item.get("damaged_quantity", 0),
                )
            GoodsReceivedItem.objects.create(
                grn=grn, accepted_quantity=accepted, **item
            )
        return grn


class SupplierBillSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)

    class Meta:
        model = SupplierBill
        fields = "__all__"

    def validate(self, attrs):
        total = attrs.get("total_amount", getattr(self.instance, "total_amount", 0))
        paid = attrs.get("paid_amount", getattr(self.instance, "paid_amount", 0))
        attrs["balance_due"] = max(Decimal("0"), total - paid)
        attrs["payment_status"] = (
            "PAID"
            if attrs["balance_due"] == 0
            else ("PARTIALLY_PAID" if paid else "UNPAID")
        )
        return attrs


class PaymentAllocationSerializer(serializers.ModelSerializer):
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = SupplierPaymentAllocation
        exclude = ["payment"]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationSerializer(many=True, required=False)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )

    class Meta:
        model = SupplierPayment
        fields = "__all__"
        read_only_fields = ["paid_by", "created_by", "updated_by"]

    @transaction.atomic
    def create(self, validated_data):
        allocations = validated_data.pop("allocations", [])
        payment = SupplierPayment.objects.create(**validated_data)
        allocated = Decimal("0")
        for allocation in allocations:
            bill = allocation["bill"]
            amount = allocation["amount"]
            if amount > bill.balance_due:
                raise serializers.ValidationError(
                    {
                        "allocations": f"Allocation exceeds balance for {bill.bill_number}."
                    }
                )
            SupplierPaymentAllocation.objects.create(payment=payment, **allocation)
            bill.paid_amount += amount
            bill.balance_due -= amount
            bill.payment_status = "PAID" if bill.balance_due == 0 else "PARTIALLY_PAID"
            bill.save(
                update_fields=[
                    "paid_amount",
                    "balance_due",
                    "payment_status",
                    "updated_at",
                ]
            )
            allocated += amount
        if allocated > payment.amount:
            raise serializers.ValidationError(
                {"allocations": "Allocated amount exceeds payment amount."}
            )
        return payment


class SupplierReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)

    class Meta:
        model = SupplierReturnItem
        exclude = ["supplier_return"]


class SupplierReturnSerializer(serializers.ModelSerializer):
    items = SupplierReturnItemSerializer(many=True, required=False)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )

    class Meta:
        model = SupplierReturn
        fields = "__all__"

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        total = sum(
            (
                Decimal(str(x.get("quantity", 0)))
                * Decimal(str(x.get("unit_price", 0)))
                for x in items
            ),
            Decimal("0"),
        )
        obj = SupplierReturn.objects.create(total_amount=total, **validated_data)
        for item in items:
            SupplierReturnItem.objects.create(
                supplier_return=obj,
                line_total=Decimal(str(item["quantity"]))
                * Decimal(str(item.get("unit_price", 0))),
                **item,
            )
        return obj


class VendorCreditApplicationSerializer(serializers.ModelSerializer):
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = VendorCreditApplication
        exclude = ["vendor_credit"]


class VendorCreditSerializer(serializers.ModelSerializer):
    applications = VendorCreditApplicationSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )

    class Meta:
        model = VendorCredit
        fields = "__all__"

    def validate(self, attrs):
        if not self.instance:
            attrs.setdefault("remaining_amount", attrs.get("total_amount", 0))
        return attrs


class PurchaseExpenseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source="supplier.supplier_name", read_only=True
    )
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)

    class Meta:
        model = PurchaseExpense
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by", "approved_by"]
