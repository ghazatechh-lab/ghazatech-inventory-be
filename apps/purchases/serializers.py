from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    GoodsReceivedItem,
    GoodsReceivedNote,
    GRNAttachment,
    PurchaseExpense,
    PurchaseExpenseAttachment,
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierBill,
    SupplierBillAttachment,
    SupplierBillItem,
    SupplierPayment,
    SupplierPaymentAttachment,
    SupplierPaymentAllocation,
    SupplierReturn,
    SupplierReturnAttachment,
    SupplierReturnItem,
    VendorCredit,
    VendorCreditAttachment,
    VendorCreditItem,
    VendorCreditApplication,
)


class POItemSerializer(
    serializers.ModelSerializer,
):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )

    sku = serializers.CharField(
        source="product.sku",
        read_only=True,
    )

    variant_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        exclude = [
            "purchase_order",
        ]
        read_only_fields = [
            "vat_amount",
            "line_total",
        ]

    def get_variant_name(
        self,
        obj,
    ):
        if not obj.variant:
            return ""

        return getattr(
            obj.variant,
            "display_name",
            None,
        ) or str(obj.variant)


class POSerializer(
    serializers.ModelSerializer,
):
    items = POItemSerializer(
        many=True,
    )

    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )

    branch_code = serializers.CharField(
        source="branch.branch_code",
        read_only=True,
    )

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    delivery_status = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = "__all__"

        read_only_fields = [
            "subtotal",
            "vat_amount",
            "total_amount",
            "created_by",
            "updated_by",
            "approved_by",
            "submitted_at",
            "approved_at",
        ]

    def get_delivery_status(
        self,
        obj,
    ):
        if obj.status == "RECEIVED":
            return "RECEIVED"

        if obj.status == "PARTIALLY_RECEIVED":
            return "PARTIAL"

        if (
            obj.expected_delivery_date
            and obj.expected_delivery_date < date.today()
            and obj.status
            not in {
                "RECEIVED",
                "CANCELLED",
            }
        ):
            return "OVERDUE"

        if obj.status == "CANCELLED":
            return "CANCELLED"

        return "PENDING"

    def _generate_po_number(
        self,
    ):
        prefix = timezone.now().strftime(
            "PO-%Y%m%d",
        )

        latest = (
            PurchaseOrder.objects.filter(
                po_number__startswith=prefix,
            )
            .order_by("-id")
            .first()
        )

        sequence = 1

        if latest:
            try:
                sequence = int(latest.po_number.split("-")[-1]) + 1
            except (
                TypeError,
                ValueError,
            ):
                sequence = (
                    PurchaseOrder.objects.filter(
                        po_number__startswith=prefix,
                    ).count()
                    + 1
                )

        return f"{prefix}-{sequence:04d}"

    def _calculate_item(
        self,
        item,
    ):
        quantity = Decimal(
            str(
                item.get(
                    "quantity",
                    0,
                )
            )
        )

        unit_price = Decimal(
            str(
                item.get(
                    "unit_price",
                    0,
                )
            )
        )

        discount = Decimal(
            str(
                item.get(
                    "discount_amount",
                    0,
                )
            )
        )

        vat_percentage = Decimal(
            str(
                item.get(
                    "vat_percentage",
                    5,
                )
            )
        )

        gross = quantity * unit_price

        taxable = max(
            Decimal("0"),
            gross - discount,
        )

        vat_amount = taxable * vat_percentage / Decimal("100")

        line_total = taxable + vat_amount

        return {
            "vat_amount": vat_amount,
            "line_total": line_total,
            "gross": gross,
        }

    def _totals(
        self,
        items,
        data,
    ):
        subtotal = Decimal("0")
        vat = Decimal("0")

        for item in items:
            values = self._calculate_item(
                item,
            )

            subtotal += values["gross"]
            vat += values["vat_amount"]

        shipping = Decimal(
            str(
                data.get(
                    "shipping_amount",
                    0,
                )
            )
        )

        other_charges = Decimal(
            str(
                data.get(
                    "other_charges",
                    0,
                )
            )
        )

        order_discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    0,
                )
            )
        )

        line_discounts = sum(
            (
                Decimal(
                    str(
                        item.get(
                            "discount_amount",
                            0,
                        )
                    )
                )
                for item in items
            ),
            Decimal("0"),
        )

        total = (
            subtotal - line_discounts - order_discount + vat + shipping + other_charges
        )

        return (
            subtotal,
            vat,
            max(
                Decimal("0"),
                total,
            ),
        )

    def validate(
        self,
        attrs,
    ):
        order_date = attrs.get(
            "order_date",
            getattr(
                self.instance,
                "order_date",
                None,
            ),
        )

        expected = attrs.get(
            "expected_delivery_date",
            getattr(
                self.instance,
                "expected_delivery_date",
                None,
            ),
        )

        if expected and order_date and expected < order_date:
            raise serializers.ValidationError(
                {
                    "expected_delivery_date": "Expected delivery cannot be before the order date."
                }
            )

        status_value = attrs.get(
            "status",
            getattr(
                self.instance,
                "status",
                "DRAFT",
            ),
        )

        if status_value not in dict(PurchaseOrder.STATUS_CHOICES):
            raise serializers.ValidationError(
                {"status": "Invalid purchase order status."}
            )

        return attrs

    def _set_workflow_dates(
        self,
        validated_data,
        instance=None,
    ):
        target_status = validated_data.get(
            "status",
            getattr(
                instance,
                "status",
                "DRAFT",
            ),
        )

        if target_status == "PENDING_APPROVAL" and not getattr(
            instance,
            "submitted_at",
            None,
        ):
            validated_data["submitted_at"] = timezone.now()

        if target_status == "APPROVED":
            validated_data["approved_at"] = timezone.now()

            request = self.context.get(
                "request",
            )

            if request and request.user.is_authenticated:
                validated_data["approved_by"] = request.user

    def _save_items(
        self,
        purchase_order,
        items,
    ):
        purchase_order.items.all().delete()

        for item in items:
            item.pop("id", None)

            values = self._calculate_item(
                item,
            )

            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order,
                vat_amount=values["vat_amount"],
                line_total=values["line_total"],
                **item,
            )

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            [],
        )

        if not items:
            raise serializers.ValidationError(
                {"items": "At least one purchase order item is required."}
            )

        po_number = (
            validated_data.get(
                "po_number",
            )
            or self._generate_po_number()
        )

        validated_data["po_number"] = po_number

        (
            subtotal,
            vat,
            total,
        ) = self._totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat,
            total_amount=total,
        )

        self._set_workflow_dates(
            validated_data,
        )

        purchase_order = PurchaseOrder.objects.create(
            **validated_data,
        )

        self._save_items(
            purchase_order,
            items,
        )

        return purchase_order

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            None,
        )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "At least one purchase order item is required."}
                )

            (
                subtotal,
                vat,
                total,
            ) = self._totals(
                items,
                validated_data,
            )

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat,
                total_amount=total,
            )

        self._set_workflow_dates(
            validated_data,
            instance,
        )

        for field, value in validated_data.items():
            setattr(
                instance,
                field,
                value,
            )

        instance.save()

        if items is not None:
            self._save_items(
                instance,
                items,
            )

        return instance


class GRNAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = GRNAttachment
        fields = [
            "id",
            "file",
            "file_url",
            "original_name",
            "file_size",
            "content_type",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class GRNItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.SerializerMethodField()
    rack_code = serializers.CharField(
        source="rack.rack_code",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = GoodsReceivedItem
        exclude = ["grn"]

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku
        return getattr(obj.product, "sku", "")

    def validate(self, attrs):
        received = attrs.get(
            "received_quantity",
            getattr(self.instance, "received_quantity", 0),
        )
        accepted = attrs.get(
            "accepted_quantity",
            getattr(self.instance, "accepted_quantity", 0),
        )
        damaged = attrs.get(
            "damaged_quantity",
            getattr(self.instance, "damaged_quantity", 0),
        )

        if accepted + damaged != received:
            raise serializers.ValidationError(
                "Accepted plus rejected quantity must equal received quantity."
            )

        return attrs


class GRNSerializer(serializers.ModelSerializer):
    items = GRNItemSerializer(many=True)
    attachments = GRNAttachmentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )
    po_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )
    received_by_name = serializers.SerializerMethodField()
    total_received_quantity = serializers.SerializerMethodField()
    total_accepted_quantity = serializers.SerializerMethodField()
    total_rejected_quantity = serializers.SerializerMethodField()
    receipt_status = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceivedNote
        fields = "__all__"
        read_only_fields = [
            "is_confirmed",
            "confirmed_at",
            "created_by",
            "updated_by",
        ]

    def get_received_by_name(self, obj):
        if not obj.received_by:
            return ""
        full_name = ""
        if hasattr(obj.received_by, "get_full_name"):
            full_name = (obj.received_by.get_full_name() or "").strip()
        return (
            full_name
            or getattr(obj.received_by, "display_name", "")
            or getattr(obj.received_by, "username", "")
            or getattr(obj.received_by, "email", "")
        )

    def get_total_received_quantity(self, obj):
        return sum(item.received_quantity for item in obj.items.all())

    def get_total_accepted_quantity(self, obj):
        return sum(item.accepted_quantity for item in obj.items.all())

    def get_total_rejected_quantity(self, obj):
        return sum(item.damaged_quantity for item in obj.items.all())

    def get_receipt_status(self, obj):
        po_items = {
            (item.product_id, item.variant_id): item
            for item in obj.purchase_order.items.all()
        }

        for item in obj.items.all():
            po_item = po_items.get((item.product_id, item.variant_id))
            if po_item and po_item.received_quantity < po_item.quantity:
                return "PARTIAL_RECEIPT"

        return "FULL_RECEIPT"

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

        if purchase_order:
            if supplier and purchase_order.supplier_id != supplier.id:
                raise serializers.ValidationError(
                    {"supplier": "Supplier must match the purchase order."}
                )
            if branch and purchase_order.branch_id != branch.id:
                raise serializers.ValidationError(
                    {"branch": "Receiving branch must match the purchase order."}
                )

        return attrs

    def _generate_number(self):
        prefix = timezone.now().strftime("GRN-%Y%m")
        count = GoodsReceivedNote.objects.filter(
            grn_number__startswith=prefix,
        ).count()
        return f"{prefix}-{count + 1:04d}"

    def _validate_items_against_po(self, purchase_order, items):
        po_items = {
            (item.product_id, item.variant_id): item
            for item in purchase_order.items.all()
        }

        for item in items:
            key = (
                item["product"].id,
                item.get("variant").id if item.get("variant") else None,
            )
            po_item = po_items.get(key)

            if not po_item:
                raise serializers.ValidationError(
                    {"items": "A received item is not part of the linked PO."}
                )

            remaining = max(0, po_item.quantity - po_item.received_quantity)

            if item["received_quantity"] > remaining:
                raise serializers.ValidationError(
                    {
                        "items": f"Received quantity for {po_item.product} exceeds the remaining PO quantity."
                    }
                )

    def _save_items(self, grn, items):
        grn.items.all().delete()

        for item in items:
            item.pop("id", None)
            item_serializer = GRNItemSerializer(data=item)
            item_serializer.is_valid(raise_exception=True)
            GoodsReceivedItem.objects.create(
                grn=grn,
                **item_serializer.validated_data,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not items:
            raise serializers.ValidationError(
                {"items": "At least one GRN item is required."}
            )

        purchase_order = validated_data["purchase_order"]
        self._validate_items_against_po(purchase_order, items)

        if not validated_data.get("grn_number"):
            validated_data["grn_number"] = self._generate_number()

        grn = GoodsReceivedNote.objects.create(**validated_data)
        self._save_items(grn, items)
        return grn

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.is_confirmed:
            raise serializers.ValidationError("A confirmed GRN cannot be edited.")

        items = validated_data.pop("items", None)

        if items is not None:
            self._validate_items_against_po(
                validated_data.get("purchase_order", instance.purchase_order),
                items,
            )

        instance = super().update(instance, validated_data)

        if items is not None:
            self._save_items(instance, items)

        return instance


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


class SupplierReturnAttachmentSerializer(
    serializers.ModelSerializer,
):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = SupplierReturnAttachment
        fields = [
            "id",
            "file",
            "file_url",
            "original_name",
            "file_size",
            "content_type",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        if not obj.file:
            return None

        request = self.context.get(
            "request",
        )

        return (
            request.build_absolute_uri(
                obj.file.url,
            )
            if request
            else obj.file.url
        )


class SupplierReturnItemSerializer(
    serializers.ModelSerializer,
):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )

    sku = serializers.SerializerMethodField()

    class Meta:
        model = SupplierReturnItem
        exclude = [
            "supplier_return",
        ]

    def get_sku(self, obj):
        if obj.variant and getattr(
            obj.variant,
            "sku",
            None,
        ):
            return obj.variant.sku

        return getattr(
            obj.product,
            "sku",
            "",
        )

    def validate(self, attrs):
        quantity = attrs.get(
            "quantity",
            getattr(
                self.instance,
                "quantity",
                0,
            ),
        )

        received = attrs.get(
            "received_quantity",
            getattr(
                self.instance,
                "received_quantity",
                None,
            ),
        )

        if quantity <= 0:
            raise serializers.ValidationError(
                {"quantity": "Return quantity must be greater than zero."}
            )

        if received is not None and quantity > received:
            raise serializers.ValidationError(
                {"quantity": "Return quantity cannot exceed accepted GRN quantity."}
            )

        return attrs


class SupplierReturnSerializer(
    serializers.ModelSerializer,
):
    items = SupplierReturnItemSerializer(
        many=True,
    )

    attachments = SupplierReturnAttachmentSerializer(
        many=True,
        read_only=True,
    )

    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )

    grn_number = serializers.CharField(
        source="grn.grn_number",
        read_only=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )

    po_number = serializers.CharField(
        source="grn.purchase_order.po_number",
        read_only=True,
    )

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    reason_display = serializers.CharField(
        source="get_reason_display",
        read_only=True,
    )

    resolution_display = serializers.CharField(
        source="get_resolution_display",
        read_only=True,
    )

    class Meta:
        model = SupplierReturn
        fields = "__all__"

        read_only_fields = [
            "approved_at",
            "approved_by",
            "submitted_at",
            "vendor_credit",
            "created_by",
            "updated_by",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime(
            "RTN-%Y%m",
        )

        count = SupplierReturn.objects.filter(
            return_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        grn = attrs.get(
            "grn",
            getattr(
                self.instance,
                "grn",
                None,
            ),
        )

        supplier = attrs.get(
            "supplier",
            getattr(
                self.instance,
                "supplier",
                None,
            ),
        )

        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        if not grn or not grn.is_confirmed:
            raise serializers.ValidationError(
                {"grn": "Only a confirmed GRN can be returned."}
            )

        if supplier and supplier.id != grn.supplier_id:
            raise serializers.ValidationError(
                {"supplier": "Supplier must match the selected GRN."}
            )

        if branch and branch.id != grn.branch_id:
            raise serializers.ValidationError(
                {"branch": "Branch must match the selected GRN."}
            )

        return attrs

    def _validate_items(
        self,
        grn,
        items,
    ):
        grn_items = {item.id: item for item in grn.items.all()}

        for item in items:
            grn_item = item.get(
                "grn_item",
            )

            if not grn_item or grn_item.id not in grn_items:
                raise serializers.ValidationError(
                    {"items": "Each return item must belong to the selected GRN."}
                )

            source = grn_items[grn_item.id]

            already_returned = (
                SupplierReturnItem.objects.filter(
                    grn_item=source,
                    supplier_return__status__in=[
                        "PENDING_APPROVAL",
                        "APPROVED",
                        "CREDIT_ISSUED",
                    ],
                )
                .exclude(
                    supplier_return=self.instance,
                )
                .aggregate(total=Sum("quantity"))["total"]
                or 0
            )

            available = max(
                0,
                source.accepted_quantity - already_returned,
            )

            if item["quantity"] > available:
                raise serializers.ValidationError(
                    {
                        "items": f"Return quantity for {source.product} exceeds the remaining returnable quantity."
                    }
                )

            if item["product"].id != source.product_id:
                raise serializers.ValidationError(
                    {"items": "Return product does not match the GRN item."}
                )

    def _save_items(
        self,
        supplier_return,
        items,
    ):
        supplier_return.items.all().delete()

        for item in items:
            item.pop("id", None)

            quantity = Decimal(str(item["quantity"]))

            unit_price = Decimal(
                str(
                    item.get(
                        "unit_price",
                        0,
                    )
                )
            )

            SupplierReturnItem.objects.create(
                supplier_return=supplier_return,
                line_total=quantity * unit_price,
                **item,
            )

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            [],
        )

        if not items:
            raise serializers.ValidationError(
                {"items": "Select at least one item to return."}
            )

        grn = validated_data["grn"]

        self._validate_items(
            grn,
            items,
        )

        if not validated_data.get(
            "return_number",
        ):
            validated_data["return_number"] = self._generate_number()

        if validated_data.get("status") == "PENDING_APPROVAL":
            validated_data["submitted_at"] = timezone.now()

        total = sum(
            (
                Decimal(str(item["quantity"]))
                * Decimal(
                    str(
                        item.get(
                            "unit_price",
                            0,
                        )
                    )
                )
                for item in items
            ),
            Decimal("0"),
        )

        supplier_return = SupplierReturn.objects.create(
            total_amount=total,
            **validated_data,
        )

        self._save_items(
            supplier_return,
            items,
        )

        return supplier_return

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        if instance.status in [
            "APPROVED",
            "CREDIT_ISSUED",
            "CANCELLED",
        ]:
            raise serializers.ValidationError(
                "Approved, credited, or cancelled returns cannot be edited."
            )

        items = validated_data.pop(
            "items",
            None,
        )

        if items is not None:
            self._validate_items(
                validated_data.get(
                    "grn",
                    instance.grn,
                ),
                items,
            )

            total = sum(
                (
                    Decimal(str(item["quantity"]))
                    * Decimal(
                        str(
                            item.get(
                                "unit_price",
                                0,
                            )
                        )
                    )
                    for item in items
                ),
                Decimal("0"),
            )

            validated_data["total_amount"] = total

        if (
            validated_data.get("status") == "PENDING_APPROVAL"
            and not instance.submitted_at
        ):
            validated_data["submitted_at"] = timezone.now()

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(
                instance,
                items,
            )

        return instance


class VendorCreditAttachmentSerializer(
    serializers.ModelSerializer,
):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = VendorCreditAttachment
        fields = [
            "id",
            "file",
            "file_url",
            "original_name",
            "file_size",
            "content_type",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        if not obj.file:
            return None

        request = self.context.get(
            "request",
        )

        return (
            request.build_absolute_uri(
                obj.file.url,
            )
            if request
            else obj.file.url
        )


class VendorCreditItemSerializer(
    serializers.ModelSerializer,
):
    gl_account_name = serializers.SerializerMethodField()

    def get_gl_account_name(self, obj):
        return obj.gl_account or ""

    class Meta:
        model = VendorCreditItem
        exclude = [
            "vendor_credit",
        ]

        read_only_fields = [
            "tax_amount",
            "line_total",
        ]


class VendorCreditApplicationSerializer(
    serializers.ModelSerializer,
):
    bill_number = serializers.CharField(
        source="bill.bill_number",
        read_only=True,
    )

    due_date = serializers.DateField(
        source="bill.due_date",
        read_only=True,
        allow_null=True,
    )

    open_balance = serializers.DecimalField(
        source="bill.balance_due",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = VendorCreditApplication
        exclude = [
            "vendor_credit",
        ]


class VendorCreditSerializer(
    serializers.ModelSerializer,
):
    items = VendorCreditItemSerializer(
        many=True,
    )

    applications = VendorCreditApplicationSerializer(
        many=True,
        required=False,
    )

    attachments = VendorCreditAttachmentSerializer(
        many=True,
        read_only=True,
    )

    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
        allow_null=True,
    )

    supplier_return_number = serializers.CharField(
        source="supplier_return.return_number",
        read_only=True,
        allow_null=True,
    )

    po_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
        allow_null=True,
    )

    bill_number = serializers.CharField(
        source="supplier_bill.bill_number",
        read_only=True,
        allow_null=True,
    )

    reason_display = serializers.CharField(
        source="get_reason_display",
        read_only=True,
    )

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = VendorCredit
        fields = "__all__"

        read_only_fields = [
            "posted_at",
            "voided_at",
            "created_by",
            "updated_by",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime(
            "VC-%Y%m",
        )

        count = VendorCredit.objects.filter(
            credit_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_item(
        self,
        item,
    ):
        quantity = Decimal(
            str(
                item.get(
                    "quantity",
                    0,
                )
            )
        )

        unit_price = Decimal(
            str(
                item.get(
                    "unit_price",
                    0,
                )
            )
        )

        tax_percentage = Decimal(
            str(
                item.get(
                    "tax_percentage",
                    0,
                )
            )
        )

        subtotal = quantity * unit_price

        tax_amount = subtotal * tax_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "line_total": subtotal + tax_amount,
        }

    def validate(self, attrs):
        supplier = attrs.get(
            "supplier",
            getattr(
                self.instance,
                "supplier",
                None,
            ),
        )

        supplier_return = attrs.get(
            "supplier_return",
            getattr(
                self.instance,
                "supplier_return",
                None,
            ),
        )

        purchase_order = attrs.get(
            "purchase_order",
            getattr(
                self.instance,
                "purchase_order",
                None,
            ),
        )

        supplier_bill = attrs.get(
            "supplier_bill",
            getattr(
                self.instance,
                "supplier_bill",
                None,
            ),
        )

        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        if not supplier:
            raise serializers.ValidationError({"supplier": "Vendor is required."})

        if supplier_return and supplier_return.supplier_id != supplier.id:
            raise serializers.ValidationError(
                {"supplier_return": "Return must belong to the selected vendor."}
            )

        if purchase_order and purchase_order.supplier_id != supplier.id:
            raise serializers.ValidationError(
                {"purchase_order": "Purchase order must belong to the selected vendor."}
            )

        if supplier_bill and supplier_bill.supplier_id != supplier.id:
            raise serializers.ValidationError(
                {"supplier_bill": "Bill must belong to the selected vendor."}
            )

        if supplier_return and branch and supplier_return.branch_id != branch.id:
            raise serializers.ValidationError(
                {"branch": "Branch must match the linked supplier return."}
            )

        return attrs

    def _validate_applications(
        self,
        supplier,
        applications,
        total_credit,
    ):
        applied_total = Decimal("0")
        seen = set()

        for application in applications:
            bill = application["bill"]

            amount = Decimal(str(application["amount"]))

            if bill.id in seen:
                raise serializers.ValidationError(
                    {"applications": "A bill cannot be selected more than once."}
                )

            seen.add(bill.id)

            if bill.supplier_id != supplier.id:
                raise serializers.ValidationError(
                    {"applications": "Every bill must belong to the selected vendor."}
                )

            if amount < 0:
                raise serializers.ValidationError(
                    {"applications": "Applied amount cannot be negative."}
                )

            if amount > bill.balance_due:
                raise serializers.ValidationError(
                    {
                        "applications": f"Application exceeds the open balance of {bill.bill_number}."
                    }
                )

            applied_total += amount

        if applied_total > total_credit:
            raise serializers.ValidationError(
                {"applications": "Applied amount cannot exceed the total credit."}
            )

        return applied_total

    def _save_items(
        self,
        vendor_credit,
        items,
    ):
        vendor_credit.items.all().delete()

        for item in items:
            item.pop("id", None)

            values = self._calculate_item(
                item,
            )

            VendorCreditItem.objects.create(
                vendor_credit=vendor_credit,
                tax_amount=values["tax_amount"],
                line_total=values["line_total"],
                **item,
            )

    def _save_applications(
        self,
        vendor_credit,
        applications,
    ):
        vendor_credit.applications.all().delete()

        for application in applications:
            application.pop(
                "id",
                None,
            )

            if application["amount"] <= 0:
                continue

            VendorCreditApplication.objects.create(
                vendor_credit=vendor_credit,
                **application,
            )

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            [],
        )

        applications = validated_data.pop(
            "applications",
            [],
        )

        if not items:
            raise serializers.ValidationError(
                {"items": "Add at least one vendor credit line."}
            )

        subtotal = Decimal("0")
        tax_amount = Decimal("0")
        total_amount = Decimal("0")

        for item in items:
            values = self._calculate_item(
                item,
            )

            subtotal += values["subtotal"]

            tax_amount += values["tax_amount"]

            total_amount += values["line_total"]

        applied_amount = self._validate_applications(
            validated_data["supplier"],
            applications,
            total_amount,
        )

        remaining_amount = max(
            Decimal("0"),
            total_amount - applied_amount,
        )

        if not validated_data.get(
            "credit_number",
        ):
            validated_data["credit_number"] = self._generate_number()

        validated_data.update(
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            applied_amount=applied_amount,
            remaining_amount=remaining_amount,
        )

        vendor_credit = VendorCredit.objects.create(
            **validated_data,
        )

        self._save_items(
            vendor_credit,
            items,
        )

        self._save_applications(
            vendor_credit,
            applications,
        )

        return vendor_credit

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        if instance.status in [
            "FULLY_APPLIED",
            "VOID",
        ]:
            raise serializers.ValidationError(
                "Fully applied or void credits cannot be edited."
            )

        items = validated_data.pop(
            "items",
            None,
        )

        applications = validated_data.pop(
            "applications",
            None,
        )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Add at least one vendor credit line."}
                )

            subtotal = Decimal("0")
            tax_amount = Decimal("0")
            total_amount = Decimal("0")

            for item in items:
                values = self._calculate_item(
                    item,
                )

                subtotal += values["subtotal"]

                tax_amount += values["tax_amount"]

                total_amount += values["line_total"]

            validated_data.update(
                subtotal=subtotal,
                tax_amount=tax_amount,
                total_amount=total_amount,
            )
        else:
            total_amount = instance.total_amount or Decimal("0")

        if applications is not None:
            applied_amount = self._validate_applications(
                validated_data.get(
                    "supplier",
                    instance.supplier,
                ),
                applications,
                total_amount,
            )

            validated_data["applied_amount"] = applied_amount

            validated_data["remaining_amount"] = max(
                Decimal("0"),
                total_amount - applied_amount,
            )

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(
                instance,
                items,
            )

        if applications is not None:
            self._save_applications(
                instance,
                applications,
            )

        return instance


class PurchaseExpenseAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseExpenseAttachment
        fields = [
            "id",
            "file",
            "file_url",
            "original_name",
            "file_size",
            "content_type",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class PurchaseExpenseSerializer(serializers.ModelSerializer):
    attachments = PurchaseExpenseAttachmentSerializer(many=True, read_only=True)
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )

    class Meta:
        model = PurchaseExpense
        fields = "__all__"
        read_only_fields = [
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "created_by",
            "updated_by",
        ]

    def validate(self, attrs):
        amount = attrs.get("amount", getattr(self.instance, "amount", 0))
        method = attrs.get(
            "payment_method", getattr(self.instance, "payment_method", None)
        )
        bank = attrs.get("bank_account", getattr(self.instance, "bank_account", None))
        cash = attrs.get("cash_register", getattr(self.instance, "cash_register", None))
        if amount is not None and amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )
        if method == "BANK_TRANSFER" and not bank:
            raise serializers.ValidationError(
                {"bank_account": "Bank account is required."}
            )
        if method in ["CASH", "PETTY_CASH"] and not cash:
            raise serializers.ValidationError(
                {"cash_register": "Cash register is required."}
            )
        return attrs

    def create(self, validated_data):
        if not validated_data.get("expense_number"):
            prefix = timezone.now().strftime("EXP-%Y%m")
            count = PurchaseExpense.objects.filter(
                expense_number__startswith=prefix
            ).count()
            validated_data["expense_number"] = f"{prefix}-{count + 1:04d}"
        return super().create(validated_data)
