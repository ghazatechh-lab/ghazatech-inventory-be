from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
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


class POItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.SerializerMethodField()
    product_image = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        exclude = ["purchase_order"]
        read_only_fields = [
            "vat_amount",
            "line_total",
            "received_quantity",
        ]

    def get_product_image(self, obj):
        image = getattr(obj.product, "image", None) or getattr(
            obj.product, "product_image", None
        )

        if not image:
            return None

        try:
            url = image.url
        except (AttributeError, ValueError):
            return None

        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku

        return getattr(obj.product, "sku", "")

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "display_name", None)
            or getattr(obj.variant, "variant_name", None)
            or str(obj.variant)
        )

    def get_total_quantity(self, obj):
        return Decimal(str(obj.quantity or 0))

    def get_remaining_quantity(self, obj):
        ordered = Decimal(str(obj.quantity or 0))
        received = Decimal(str(obj.received_quantity or 0))

        return max(
            Decimal("0"),
            ordered - received,
        )

    def validate(self, attrs):
        quantity = Decimal(
            str(
                attrs.get(
                    "quantity",
                    getattr(self.instance, "quantity", 0),
                )
                or 0
            )
        )

        unit_price = Decimal(
            str(
                attrs.get(
                    "unit_price",
                    getattr(self.instance, "unit_price", 0),
                )
                or 0
            )
        )

        discount_amount = Decimal(
            str(
                attrs.get(
                    "discount_amount",
                    getattr(self.instance, "discount_amount", 0),
                )
                or 0
            )
        )

        tax_treatment = str(
            attrs.get(
                "tax_treatment",
                getattr(
                    self.instance,
                    "tax_treatment",
                    "STANDARD_VAT",
                ),
            )
            or "STANDARD_VAT"
        ).upper()

        vat_percentage = Decimal(
            str(
                attrs.get(
                    "vat_percentage",
                    getattr(self.instance, "vat_percentage", 5),
                )
                or 0
            )
        )

        errors = {}

        if quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if unit_price < 0:
            errors["unit_price"] = "Unit price cannot be negative."

        if discount_amount < 0:
            errors["discount_amount"] = "Discount cannot be negative."

        gross = quantity * unit_price

        if discount_amount > gross:
            errors["discount_amount"] = "Discount cannot exceed the line amount."

        if tax_treatment != "STANDARD_VAT":
            attrs["vat_percentage"] = Decimal("0")
        elif vat_percentage < 0:
            errors["vat_percentage"] = "VAT percentage cannot be negative."

        attrs["quantity"] = quantity

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class POSerializer(serializers.ModelSerializer):
    items = POItemSerializer(many=True)

    po_number = serializers.CharField(
        read_only=True,
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
    approved_by_name = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )
    delivery_status = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    allowed_statuses = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = [
            "po_number",
            "subtotal",
            "vat_amount",
            "total_amount",
            "created_by",
            "updated_by",
            "approved_by",
            "submitted_at",
            "approved_at",
        ]

    def get_approved_by_name(self, obj):
        user = obj.approved_by

        if not user:
            return ""

        if hasattr(user, "get_full_name"):
            full_name = (user.get_full_name() or "").strip()

            if full_name:
                return full_name

        return (
            getattr(user, "display_name", None)
            or getattr(user, "name", None)
            or getattr(user, "email", None)
            or getattr(user, "username", None)
            or str(user)
        )

    def get_delivery_status(self, obj):
        if obj.status == "RECEIVED":
            return "RECEIVED"

        if obj.status == "PARTIALLY_RECEIVED":
            return "PARTIAL"

        if (
            obj.expected_delivery_date
            and obj.expected_delivery_date < timezone.localdate()
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

    def get_allowed_statuses(self, obj):
        transitions = {
            "DRAFT": [
                "PENDING_APPROVAL",
                "CANCELLED",
            ],
            "PENDING_APPROVAL": [
                "DRAFT",
                "APPROVED",
                "CANCELLED",
            ],
            "APPROVED": [
                "PARTIALLY_RECEIVED",
                "RECEIVED",
                "CANCELLED",
            ],
            "PARTIALLY_RECEIVED": [
                "RECEIVED",
                "CANCELLED",
            ],
            "RECEIVED": [],
            "CANCELLED": [],
        }

        return transitions.get(obj.status, [])

    def _generate_po_number(self):
        prefix = timezone.localdate().strftime("PO-%Y%m%d")

        latest = (
            PurchaseOrder.objects.select_for_update()
            .filter(
                po_number__startswith=f"{prefix}-",
            )
            .order_by("-id")
            .first()
        )

        sequence = 1

        if latest and latest.po_number:
            try:
                sequence = int(latest.po_number.rsplit("-", 1)[-1]) + 1
            except (TypeError, ValueError):
                sequence = (
                    PurchaseOrder.objects.filter(
                        po_number__startswith=f"{prefix}-",
                    ).count()
                    + 1
                )

        candidate = f"{prefix}-{sequence:04d}"

        while PurchaseOrder.objects.filter(po_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}-{sequence:04d}"

        return candidate

    def _calculate_item(self, item):
        quantity = Decimal(str(item.get("quantity", 0) or 0))
        unit_price = Decimal(str(item.get("unit_price", 0) or 0))
        discount = Decimal(str(item.get("discount_amount", 0) or 0))
        vat_percentage = Decimal(str(item.get("vat_percentage", 5) or 0))

        gross = quantity * unit_price
        taxable = max(
            Decimal("0"),
            gross - discount,
        )
        vat_amount = taxable * vat_percentage / Decimal("100")
        line_total = taxable + vat_amount

        return {
            "gross": gross,
            "taxable": taxable,
            "vat_amount": vat_amount,
            "line_total": line_total,
        }

    def _totals(self, items, data):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")
        line_discounts = Decimal("0")

        for item in items:
            values = self._calculate_item(item)

            subtotal += values["gross"]
            vat_amount += values["vat_amount"]
            line_discounts += Decimal(
                str(
                    item.get(
                        "discount_amount",
                        0,
                    )
                    or 0
                )
            )

        shipping_amount = Decimal(str(data.get("shipping_amount", 0) or 0))
        other_charges = Decimal(str(data.get("other_charges", 0) or 0))
        order_discount = Decimal(str(data.get("discount_amount", 0) or 0))

        total_amount = (
            subtotal
            - line_discounts
            - order_discount
            + vat_amount
            + shipping_amount
            + other_charges
        )

        return (
            subtotal,
            vat_amount,
            max(
                Decimal("0"),
                total_amount,
            ),
        )

    def validate(self, attrs):
        order_date = attrs.get(
            "order_date",
            getattr(
                self.instance,
                "order_date",
                None,
            ),
        )
        expected_delivery_date = attrs.get(
            "expected_delivery_date",
            getattr(
                self.instance,
                "expected_delivery_date",
                None,
            ),
        )
        status_value = attrs.get(
            "status",
            getattr(
                self.instance,
                "status",
                "DRAFT",
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
        supplier = attrs.get(
            "supplier",
            getattr(
                self.instance,
                "supplier",
                None,
            ),
        )

        errors = {}

        if not branch:
            errors["branch"] = "Branch is required."

        if not supplier:
            errors["supplier"] = "Supplier is required."

        if not order_date:
            errors["order_date"] = "Order date is required."

        if (
            expected_delivery_date
            and order_date
            and expected_delivery_date < order_date
        ):
            errors["expected_delivery_date"] = (
                "Expected delivery cannot be before the order date."
            )

        if status_value not in dict(PurchaseOrder.STATUS_CHOICES):
            errors["status"] = "Invalid purchase order status."

        if errors:
            raise serializers.ValidationError(errors)

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

            request = self.context.get("request")

            if request and request.user and request.user.is_authenticated:
                validated_data["approved_by"] = request.user

    def _save_items(
        self,
        purchase_order,
        items,
    ):
        purchase_order.items.all().delete()

        for raw_item in items:
            item = dict(raw_item)
            item.pop("id", None)
            item.pop("received_quantity", None)

            values = self._calculate_item(item)

            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order,
                vat_amount=values["vat_amount"],
                line_total=values["line_total"],
                **item,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop(
            "items",
            [],
        )

        if not items:
            raise serializers.ValidationError(
                {"items": ("At least one purchase order item is required.")}
            )

        validated_data.pop("po_number", None)
        validated_data["po_number"] = self._generate_po_number()

        (
            subtotal,
            vat_amount,
            total_amount,
        ) = self._totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total_amount,
        )

        self._set_workflow_dates(validated_data)

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

        validated_data.pop("po_number", None)

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("At least one purchase order item is required.")}
                )

            (
                subtotal,
                vat_amount,
                total_amount,
            ) = self._totals(
                items,
                validated_data,
            )

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total_amount,
            )

        self._set_workflow_dates(
            validated_data,
            instance,
        )

        for field, value in validated_data.items():
            setattr(instance, field, value)

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

        regular_received = (
            attrs.get(
                "regular_received_quantity",
                getattr(self.instance, "regular_received_quantity", 0),
            )
            or 0
        )
        restricted_received = (
            attrs.get(
                "restricted_received_quantity",
                getattr(self.instance, "restricted_received_quantity", 0),
            )
            or 0
        )
        regular_accepted = (
            attrs.get(
                "regular_accepted_quantity",
                getattr(self.instance, "regular_accepted_quantity", 0),
            )
            or 0
        )
        restricted_accepted = (
            attrs.get(
                "restricted_accepted_quantity",
                getattr(self.instance, "restricted_accepted_quantity", 0),
            )
            or 0
        )
        if regular_received or restricted_received:
            attrs["received_quantity"] = regular_received + restricted_received
            attrs["accepted_quantity"] = regular_accepted + restricted_accepted
            received = attrs["received_quantity"]
            accepted = attrs["accepted_quantity"]
        if accepted + damaged + (attrs.get("rejected_quantity", 0) or 0) != received:
            raise serializers.ValidationError(
                "Accepted, damaged, and rejected quantities must equal received quantity."
            )
        return attrs


class GRNSerializer(serializers.ModelSerializer):
    # Generated automatically by the backend. The frontend must not be
    # required to submit a GRN number.
    grn_number = serializers.CharField(
        read_only=True,
    )
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
            "grn_number",
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
        """
        Save GRN items that have already passed nested serializer validation.

        DRF converts product, variant, and other related primary keys into
        model instances during GRNSerializer validation. Re-validating those
        model instances through GRNItemSerializer(data=item) makes
        PrimaryKeyRelatedField interpret the model objects as submitted IDs,
        resulting in errors such as:

        - Select a valid product.
        - Select a valid variant.

        Save the validated dictionaries directly instead.
        """
        grn.items.all().delete()

        for raw_item in items:
            item = dict(raw_item)

            item.pop("id", None)
            item.pop("grn", None)

            GoodsReceivedItem.objects.create(
                grn=grn,
                **item,
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


class SupplierBillItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    available_bill_quantity = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillItem
        fields = [
            "id",
            "grn_item",
            "product",
            "product_name",
            "variant",
            "variant_name",
            "sku",
            "received_quantity",
            "bill_quantity",
            "available_bill_quantity",
            "unit_cost",
            "discount_amount",
            "vat_percentage",
            "vat_amount",
            "line_total",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "variant_name",
            "sku",
            "available_bill_quantity",
            "vat_amount",
            "line_total",
        ]

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku
        return getattr(obj.product, "sku", "") if obj.product else ""

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""
        return (
            getattr(obj.variant, "display_name", "")
            or getattr(obj.variant, "variant_name", "")
            or getattr(obj.variant, "name", "")
            or str(obj.variant)
        )

    def _already_billed_quantity(self, grn_item, exclude_bill_id=None):
        queryset = SupplierBillItem.objects.filter(
            grn_item=grn_item,
        ).exclude(
            bill__status="CANCELLED",
        )

        if exclude_bill_id not in (None, "", "null"):
            queryset = queryset.exclude(
                bill_id=exclude_bill_id,
            )

        return int(queryset.aggregate(total=Sum("bill_quantity"))["total"] or 0)

    def get_available_bill_quantity(self, obj):
        if not obj.grn_item_id:
            return 0

        accepted = int(
            obj.grn_item.accepted_quantity or obj.grn_item.received_quantity or 0
        )
        billed_elsewhere = self._already_billed_quantity(
            obj.grn_item,
            exclude_bill_id=obj.bill_id,
        )
        return max(0, accepted - billed_elsewhere)

    def validate(self, attrs):
        grn_item = attrs.get(
            "grn_item",
            getattr(self.instance, "grn_item", None),
        )
        product = attrs.get(
            "product",
            getattr(self.instance, "product", None),
        )
        variant = attrs.get(
            "variant",
            getattr(self.instance, "variant", None),
        )

        bill_quantity = int(
            attrs.get(
                "bill_quantity",
                getattr(self.instance, "bill_quantity", 0),
            )
            or 0
        )
        unit_cost = Decimal(
            str(
                attrs.get(
                    "unit_cost",
                    getattr(self.instance, "unit_cost", 0),
                )
                or 0
            )
        )
        discount_amount = Decimal(
            str(
                attrs.get(
                    "discount_amount",
                    getattr(self.instance, "discount_amount", 0),
                )
                or 0
            )
        )
        vat_percentage = Decimal(
            str(
                attrs.get(
                    "vat_percentage",
                    getattr(self.instance, "vat_percentage", 5),
                )
                or 0
            )
        )

        errors = {}

        if not grn_item:
            errors["grn_item"] = "GRN item is required."

        if not product:
            errors["product"] = "Product is required."

        if grn_item and product and grn_item.product_id != product.id:
            errors["product"] = "Product must match the selected GRN item."

        grn_variant_id = grn_item.variant_id if grn_item else None
        variant_id = variant.id if variant else None

        if grn_item and grn_variant_id != variant_id:
            errors["variant"] = "Variant must match the selected GRN item."

        accepted_quantity = 0
        available_quantity = 0

        if grn_item:
            accepted_quantity = int(
                grn_item.accepted_quantity or grn_item.received_quantity or 0
            )
            exclude_bill_id = (
                self.instance.bill_id
                if self.instance is not None
                else self.context.get("supplier_bill_id")
            )
            billed_elsewhere = self._already_billed_quantity(
                grn_item,
                exclude_bill_id=exclude_bill_id,
            )
            available_quantity = max(
                0,
                accepted_quantity - billed_elsewhere,
            )

            attrs["received_quantity"] = accepted_quantity

        if bill_quantity <= 0:
            errors["bill_quantity"] = "Bill quantity must be greater than zero."
        elif grn_item and bill_quantity > available_quantity:
            errors["bill_quantity"] = (
                "Bill quantity cannot exceed the remaining unbilled "
                f"GRN quantity ({available_quantity})."
            )

        if unit_cost < 0:
            errors["unit_cost"] = "Unit cost cannot be negative."

        gross = Decimal(bill_quantity) * unit_cost

        if discount_amount < 0:
            errors["discount_amount"] = "Discount cannot be negative."
        elif discount_amount > gross:
            errors["discount_amount"] = "Discount cannot exceed the gross line amount."

        if vat_percentage < 0:
            errors["vat_percentage"] = "VAT percentage cannot be negative."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["bill_quantity"] = bill_quantity
        attrs["unit_cost"] = unit_cost
        attrs["discount_amount"] = discount_amount
        attrs["vat_percentage"] = vat_percentage
        return attrs


class SupplierBillAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillAttachment
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


class SupplierBillSerializer(serializers.ModelSerializer):
    bill_number = serializers.CharField(read_only=True)

    def to_internal_value(self, data):
        """
        Supplier Bill approval is handled only by the dedicated approve action.

        Older frontend versions may submit PENDING_APPROVAL or APPROVED even
        when those values are not part of SupplierBill.STATUS_CHOICES. Convert
        them to DRAFT before DRF's ChoiceField validation runs.
        """
        mutable_data = data.copy() if hasattr(data, "copy") else dict(data)

        requested_status = (
            str(mutable_data.get("status", "DRAFT") or "DRAFT").strip().upper()
        )

        valid_statuses = {value for value, _label in SupplierBill.STATUS_CHOICES}

        if requested_status in {
            "PENDING_APPROVAL",
            "APPROVED",
        }:
            mutable_data["status"] = "DRAFT"
        elif requested_status not in valid_statuses:
            mutable_data["status"] = "DRAFT"

        return super().to_internal_value(mutable_data)

    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )
    po_number = serializers.CharField(
        source="purchase_order.po_number",
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

    items = SupplierBillItemSerializer(
        many=True,
        required=True,
    )
    attachments = SupplierBillAttachmentSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = SupplierBill
        fields = "__all__"
        read_only_fields = [
            "bill_number",
            "subtotal",
            "vat_amount",
            "total_amount",
            "balance_due",
            "match_status",
            "approved_by",
            "approved_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def _generate_number(self):
        prefix = timezone.localdate().strftime("SB-%Y%m-")
        last_bill = (
            SupplierBill.objects.select_for_update()
            .filter(bill_number__startswith=prefix)
            .order_by("-bill_number")
            .values_list("bill_number", flat=True)
            .first()
        )

        sequence = 1
        if last_bill:
            try:
                sequence = int(last_bill.rsplit("-", 1)[-1]) + 1
            except (TypeError, ValueError):
                sequence = (
                    SupplierBill.objects.filter(
                        bill_number__startswith=prefix,
                    ).count()
                    + 1
                )

        candidate = f"{prefix}{sequence:04d}"
        while SupplierBill.objects.filter(bill_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"
        return candidate

    def validate(self, attrs):
        purchase_order = attrs.get(
            "purchase_order",
            getattr(self.instance, "purchase_order", None),
        )
        grn = attrs.get(
            "grn",
            getattr(self.instance, "grn", None),
        )
        supplier = attrs.get(
            "supplier",
            getattr(self.instance, "supplier", None),
        )
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )
        requested_status = str(
            attrs.get(
                "status",
                getattr(self.instance, "status", "DRAFT"),
            )
            or "DRAFT"
        ).upper()

        errors = {}

        if self.instance and self.instance.approved_at:
            errors["status"] = "Approved Supplier Bills cannot be edited."

        editable_statuses = {
            value
            for value, _label in SupplierBill.STATUS_CHOICES
            if value in {"DRAFT", "UNMATCHED"}
        }

        if requested_status not in editable_statuses:
            errors["status"] = "Use the approval action to approve a Supplier Bill."

        if not purchase_order:
            errors["purchase_order"] = "Purchase Order Reference is required."

        if not grn:
            errors["grn"] = "A confirmed GRN is required."

        if purchase_order:
            if not supplier:
                attrs["supplier"] = purchase_order.supplier
                supplier = purchase_order.supplier

            if not branch:
                attrs["branch"] = purchase_order.branch
                branch = purchase_order.branch

            if purchase_order.supplier_id != supplier.id:
                errors["supplier"] = "Supplier must match the selected Purchase Order."

            if purchase_order.branch_id != branch.id:
                errors["branch"] = "Branch must match the selected Purchase Order."

        if grn:
            if not grn.is_confirmed:
                errors["grn"] = "Only a confirmed GRN can be used for a Supplier Bill."

            if purchase_order and grn.purchase_order_id != purchase_order.id:
                errors["grn"] = (
                    "The selected GRN does not belong to the "
                    "selected Purchase Order."
                )

            if supplier and grn.supplier_id != supplier.id:
                errors["supplier"] = "Supplier must match the selected GRN."

            if branch and grn.branch_id != branch.id:
                errors["branch"] = "Branch must match the selected GRN."

        supplier_invoice_number = str(
            attrs.get(
                "supplier_invoice_number",
                getattr(
                    self.instance,
                    "supplier_invoice_number",
                    "",
                ),
            )
            or ""
        ).strip()

        if not supplier_invoice_number:
            errors["supplier_invoice_number"] = "Supplier invoice number is required."
        elif supplier:
            duplicate_query = SupplierBill.objects.filter(
                supplier=supplier,
                supplier_invoice_number__iexact=(supplier_invoice_number),
            )
            if self.instance:
                duplicate_query = duplicate_query.exclude(pk=self.instance.pk)
            if duplicate_query.exists():
                errors["supplier_invoice_number"] = (
                    "This supplier invoice number already exists "
                    "for the selected supplier."
                )

        bill_date = attrs.get(
            "bill_date",
            getattr(self.instance, "bill_date", None),
        )
        due_date = attrs.get(
            "due_date",
            getattr(self.instance, "due_date", None),
        )

        if bill_date and due_date and due_date < bill_date:
            errors["due_date"] = "Due date cannot be before the bill date."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["supplier_invoice_number"] = supplier_invoice_number
        attrs["paid_amount"] = (
            getattr(self.instance, "paid_amount", Decimal("0"))
            if self.instance
            else Decimal("0")
        )
        return attrs

    def _calculate_item_values(self, item):
        bill_quantity = int(item["bill_quantity"])
        received_quantity = int(item["received_quantity"])
        unit_cost = Decimal(str(item["unit_cost"]))
        discount_amount = Decimal(str(item.get("discount_amount", 0) or 0))
        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        gross = Decimal(bill_quantity) * unit_cost
        taxable = max(
            Decimal("0"),
            gross - discount_amount,
        )
        vat_amount = taxable * vat_percentage / Decimal("100")

        return {
            "received_quantity": received_quantity,
            "bill_quantity": bill_quantity,
            "unit_cost": unit_cost,
            "discount_amount": discount_amount,
            "vat_percentage": vat_percentage,
            "subtotal": taxable,
            "vat_amount": vat_amount,
            "line_total": taxable + vat_amount,
        }

    def _save_items(self, bill, items):
        bill.items.all().delete()

        subtotal = Decimal("0")
        vat_amount = Decimal("0")
        item_total = Decimal("0")

        for raw_item in items:
            item = dict(raw_item)

            for field in (
                "id",
                "available_bill_quantity",
                "quantity",
                "unit_price",
                "subtotal",
                "product_name",
                "variant_name",
                "sku",
            ):
                item.pop(field, None)

            values = self._calculate_item_values(item)

            SupplierBillItem.objects.create(
                bill=bill,
                grn_item=item["grn_item"],
                product=item["product"],
                variant=item.get("variant"),
                received_quantity=values["received_quantity"],
                bill_quantity=values["bill_quantity"],
                unit_cost=values["unit_cost"],
                discount_amount=values["discount_amount"],
                vat_percentage=values["vat_percentage"],
                vat_amount=values["vat_amount"],
                line_total=values["line_total"],
            )

            subtotal += values["subtotal"]
            vat_amount += values["vat_amount"]
            item_total += values["line_total"]

        header_discount = Decimal(str(bill.discount_amount or 0))

        if header_discount < 0:
            raise serializers.ValidationError(
                {"discount_amount": "Discount cannot be negative."}
            )

        if header_discount > item_total:
            raise serializers.ValidationError(
                {
                    "discount_amount": (
                        "Additional discount cannot exceed the " "bill amount."
                    )
                }
            )

        total_amount = max(
            Decimal("0"),
            item_total - header_discount,
        )

        bill.subtotal = subtotal
        bill.vat_amount = vat_amount
        bill.total_amount = total_amount
        bill.paid_amount = Decimal("0")
        bill.balance_due = total_amount
        bill.match_status = "PENDING"
        bill.save(
            update_fields=[
                "subtotal",
                "vat_amount",
                "total_amount",
                "paid_amount",
                "balance_due",
                "match_status",
                "updated_at",
            ]
        )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        if not items:
            raise serializers.ValidationError(
                {"items": ("At least one Supplier Bill item is required.")}
            )

        validated_data.pop("bill_number", None)
        validated_data["bill_number"] = self._generate_number()
        validated_data["paid_amount"] = Decimal("0")
        validated_data["balance_due"] = Decimal("0")
        validated_data["match_status"] = "PENDING"

        bill = SupplierBill.objects.create(**validated_data)

        # Nested item data has already been validated by DRF. Related fields
        # such as product and grn_item are model instances at this point.
        self._save_items(
            bill,
            items,
        )

        return bill

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.approved_at:
            raise serializers.ValidationError(
                {"status": "Approved Supplier Bills cannot be edited."}
            )

        items = validated_data.pop("items", None)
        validated_data.pop("bill_number", None)
        validated_data.pop("paid_amount", None)

        instance = super().update(instance, validated_data)

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("At least one Supplier Bill item is required.")}
                )

            # Do not revalidate model instances as raw primary keys.
            self._save_items(
                instance,
                items,
            )

        return instance


class SupplierBillItemDetailSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )

    variant_name = serializers.SerializerMethodField()
    sku = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillItem
        fields = [
            "id",
            "product",
            "product_name",
            "variant",
            "variant_name",
            "sku",
            "received_quantity",
            "bill_quantity",
            "quantity",
            "unit_cost",
            "unit_price",
            "discount_amount",
            "vat_percentage",
            "vat_amount",
            "subtotal",
            "line_total",
            "grn_item",
        ]

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "display_name", "")
            or getattr(obj.variant, "variant_name", "")
            or getattr(obj.variant, "name", "")
            or str(obj.variant)
        )

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku

        return getattr(obj.product, "sku", "") if obj.product else ""

    def get_quantity(self, obj):
        return obj.bill_quantity

    def get_unit_price(self, obj):
        return obj.unit_cost

    def get_subtotal(self, obj):
        quantity = obj.bill_quantity or 0
        unit_cost = obj.unit_cost or 0
        discount = obj.discount_amount or 0

        return max((quantity * unit_cost) - discount, 0)


class SupplierBillAttachmentDetailSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillAttachment
        fields = [
            "id",
            "file",
            "file_url",
            "file_name",
            "original_name",
            "file_size",
            "content_type",
            "created_at",
        ]

    def get_file_url(self, obj):
        if not obj.file:
            return ""

        request = self.context.get("request")
        url = obj.file.url

        return request.build_absolute_uri(url) if request else url

    def get_file_name(self, obj):
        if obj.original_name:
            return obj.original_name

        return obj.file.name.rsplit("/", 1)[-1] if obj.file else ""


class SupplierBillPaymentAllocationSerializer(serializers.ModelSerializer):
    payment_number = serializers.CharField(
        source="payment.payment_number",
        read_only=True,
    )

    payment_date = serializers.DateField(
        source="payment.payment_date",
        read_only=True,
    )

    payment_method = serializers.CharField(
        source="payment.payment_method",
        read_only=True,
    )

    reference_number = serializers.CharField(
        source="payment.reference_number",
        read_only=True,
    )

    class Meta:
        model = SupplierPaymentAllocation
        fields = [
            "id",
            "payment",
            "payment_number",
            "payment_date",
            "payment_method",
            "reference_number",
            "amount",
        ]


class SupplierBillDetailSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )

    supplier_code = serializers.CharField(
        source="supplier.supplier_code",
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

    po_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
    )

    grn_number = serializers.CharField(
        source="grn.grn_number",
        read_only=True,
    )

    approved_by_name = serializers.SerializerMethodField()

    items = SupplierBillItemDetailSerializer(
        many=True,
        read_only=True,
    )

    attachments = SupplierBillAttachmentDetailSerializer(
        many=True,
        read_only=True,
    )

    payment_allocations = SupplierBillPaymentAllocationSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = SupplierBill
        fields = [
            "id",
            "bill_number",
            "supplier_invoice_number",
            "supplier",
            "supplier_name",
            "supplier_code",
            "branch",
            "branch_name",
            "branch_code",
            "purchase_order",
            "po_number",
            "grn",
            "grn_number",
            "bill_date",
            "due_date",
            "payment_terms_days",
            "currency",
            "subtotal",
            "discount_amount",
            "vat_amount",
            "total_amount",
            "paid_amount",
            "balance_due",
            "status",
            "match_status",
            "notes",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "items",
            "attachments",
            "payment_allocations",
            "created_at",
            "updated_at",
        ]

    def get_approved_by_name(self, obj):
        user = obj.approved_by

        if not user:
            return ""

        full_name = user.get_full_name() if hasattr(user, "get_full_name") else ""

        return (
            full_name
            or getattr(user, "username", "")
            or getattr(
                user,
                "email",
                "",
            )
        )


class SupplierPaymentAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPaymentAttachment
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


class PaymentAllocationSerializer(serializers.ModelSerializer):
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = SupplierPaymentAllocation
        exclude = ["payment"]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    payment_number = serializers.CharField(read_only=True)
    paid_by_name = serializers.SerializerMethodField()

    allocations = PaymentAllocationSerializer(
        many=True,
        required=False,
    )
    attachments = SupplierPaymentAttachmentSerializer(
        many=True,
        read_only=True,
    )
    supplier_name = serializers.CharField(
        source="supplier.supplier_name",
        read_only=True,
    )

    class Meta:
        model = SupplierPayment
        fields = "__all__"
        read_only_fields = [
            "payment_number",
            "paid_by",
            "created_by",
            "updated_by",
        ]

    def get_paid_by_name(self, obj):
        user = obj.paid_by

        if not user:
            return ""

        full_name = (
            user.get_full_name().strip() if hasattr(user, "get_full_name") else ""
        )

        return (
            full_name
            or getattr(user, "display_name", "")
            or getattr(user, "username", "")
            or getattr(user, "email", "")
        )

    def _generate_payment_number(self, branch):
        """
        Generate a branch-specific sequential payment number.

        Locking the branch row ensures that two requests for the same branch
        cannot calculate the same next sequence concurrently.
        """
        from apps.branches.models import Branch

        locked_branch = Branch.objects.select_for_update().get(
            pk=branch.pk,
        )

        branch_code = (
            str(getattr(locked_branch, "branch_code", "") or f"B{locked_branch.pk}")
            .strip()
            .upper()
            .replace(" ", "")
        )

        prefix = f"SP-{branch_code}-" f"{timezone.localdate():%Y%m}-"

        latest_number = (
            SupplierPayment.objects.filter(
                payment_number__startswith=prefix,
            )
            .order_by("-payment_number")
            .values_list("payment_number", flat=True)
            .first()
        )

        sequence = 1

        if latest_number:
            try:
                sequence = int(latest_number.rsplit("-", 1)[-1]) + 1
            except (TypeError, ValueError):
                sequence = (
                    SupplierPayment.objects.filter(
                        payment_number__startswith=prefix,
                    ).count()
                    + 1
                )

        candidate = f"{prefix}{sequence:04d}"

        while SupplierPayment.objects.filter(
            payment_number=candidate,
        ).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"

        return candidate

    def validate(self, attrs):
        supplier = attrs.get(
            "supplier",
            getattr(self.instance, "supplier", None),
        )
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )
        payment_method = attrs.get(
            "payment_method",
            getattr(self.instance, "payment_method", None),
        )
        bank_account = attrs.get(
            "bank_account",
            getattr(self.instance, "bank_account", None),
        )
        cash_register = attrs.get(
            "cash_register",
            getattr(self.instance, "cash_register", None),
        )
        amount = Decimal(
            str(
                attrs.get(
                    "amount",
                    getattr(self.instance, "amount", 0),
                )
                or 0
            )
        )

        errors = {}

        if not supplier:
            errors["supplier"] = "Supplier is required."

        if not branch:
            errors["branch"] = "Branch is required."

        if (
            supplier
            and branch
            and getattr(supplier, "branch_id", None)
            and supplier.branch_id != branch.id
        ):
            errors["supplier"] = "Supplier must belong to the selected branch."

        if amount <= Decimal("0.00"):
            errors["amount"] = "Payment amount must be greater than zero."

        if payment_method == "CASH":
            if not cash_register:
                errors["cash_register"] = "Cash register is required for cash payments."
            attrs["bank_account"] = None

        elif payment_method in {
            "BANK_TRANSFER",
            "CHEQUE",
            "CARD",
        }:
            if not bank_account:
                errors["bank_account"] = (
                    "Bank account is required for this payment method."
                )
            attrs["cash_register"] = None

        if payment_method == "CHEQUE":
            cheque_number = str(
                attrs.get(
                    "cheque_number",
                    getattr(self.instance, "cheque_number", ""),
                )
                or ""
            ).strip()
            cheque_date = attrs.get(
                "cheque_date",
                getattr(self.instance, "cheque_date", None),
            )

            if not cheque_number:
                errors["cheque_number"] = "Cheque number is required."
            if not cheque_date:
                errors["cheque_date"] = "Cheque date is required."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["amount"] = amount
        return attrs

    def _validate_allocations(
        self,
        *,
        allocations,
        supplier,
        branch,
        payment_amount,
    ):
        if not allocations:
            raise serializers.ValidationError(
                {
                    "allocations": (
                        "Allocate the payment to at least one " "Supplier Bill."
                    )
                }
            )

        bill_ids = [allocation["bill"].pk for allocation in allocations]

        if len(bill_ids) != len(set(bill_ids)):
            raise serializers.ValidationError(
                {
                    "allocations": (
                        "The same Supplier Bill cannot be " "allocated more than once."
                    )
                }
            )

        locked_bills = {
            bill.pk: bill
            for bill in SupplierBill.objects.select_for_update().filter(pk__in=bill_ids)
        }

        allocated_total = Decimal("0.00")
        prepared = []

        for index, allocation in enumerate(allocations):
            bill = locked_bills.get(allocation["bill"].pk)

            if not bill:
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation {index + 1}: Supplier Bill " "was not found."
                        )
                    }
                )

            if bill.supplier_id != supplier.id:
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation {index + 1}: "
                            f"{bill.bill_number} belongs to another "
                            "supplier."
                        )
                    }
                )

            if bill.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation {index + 1}: "
                            f"{bill.bill_number} belongs to another "
                            "branch."
                        )
                    }
                )

            if bill.status == "CANCELLED":
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation {index + 1}: cancelled bill "
                            f"{bill.bill_number} cannot receive a payment."
                        )
                    }
                )

            amount = Decimal(str(allocation.get("amount", 0) or 0))

            if amount <= Decimal("0.00"):
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation {index + 1}: amount must be "
                            "greater than zero."
                        )
                    }
                )

            current_balance = Decimal(
                str(
                    bill.balance_due
                    if bill.balance_due is not None
                    else bill.total_amount or 0
                )
            )

            if amount > current_balance:
                raise serializers.ValidationError(
                    {
                        "allocations": (
                            f"Allocation for {bill.bill_number} "
                            f"exceeds its available balance of "
                            f"{current_balance:.2f}."
                        )
                    }
                )

            allocated_total += amount
            prepared.append((bill, amount))

        if allocated_total > payment_amount:
            raise serializers.ValidationError(
                {
                    "allocations": (
                        "Total allocated amount cannot exceed the " "payment amount."
                    )
                }
            )

        # Require complete allocation to prevent unexplained payment balances.
        if allocated_total != payment_amount:
            raise serializers.ValidationError(
                {
                    "allocations": (
                        "Total allocated amount must equal the "
                        f"payment amount ({payment_amount:.2f})."
                    )
                }
            )

        return prepared

    @transaction.atomic
    def create(self, validated_data):
        allocations = validated_data.pop(
            "allocations",
            [],
        )

        # Never accept an empty/old frontend-generated number.
        validated_data.pop("payment_number", None)

        supplier = validated_data["supplier"]
        branch = validated_data["branch"]
        payment_amount = Decimal(str(validated_data.get("amount", 0) or 0))

        prepared_allocations = self._validate_allocations(
            allocations=allocations,
            supplier=supplier,
            branch=branch,
            payment_amount=payment_amount,
        )

        validated_data["payment_number"] = self._generate_payment_number(branch)

        payment = SupplierPayment.objects.create(**validated_data)

        for bill, amount in prepared_allocations:
            SupplierPaymentAllocation.objects.create(
                payment=payment,
                bill=bill,
                amount=amount,
            )

            paid_amount = Decimal(str(bill.paid_amount or 0)) + amount
            total_amount = Decimal(str(bill.total_amount or 0))
            balance_due = max(
                Decimal("0.00"),
                total_amount - paid_amount,
            )

            bill.paid_amount = paid_amount
            bill.balance_due = balance_due
            bill.status = "PAID" if balance_due == Decimal("0.00") else "PARTIALLY_PAID"
            bill.save(
                update_fields=[
                    "paid_amount",
                    "balance_due",
                    "status",
                    "updated_at",
                ]
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


class SupplierReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
    )
    sku = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = SupplierReturnItem
        fields = [
            "id",
            "grn_item",
            "product",
            "product_name",
            "variant",
            "sku",
            "received_quantity",
            "available_quantity",
            "quantity",
            "unit_price",
            "tax_treatment",
            "vat_percentage",
            "vat_amount",
            "line_total",
            "reason",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "sku",
            "available_quantity",
            "vat_amount",
            "line_total",
        ]

    def get_sku(self, obj):
        if obj.variant and getattr(obj.variant, "sku", None):
            return obj.variant.sku

        return getattr(obj.product, "sku", "")

    def _already_returned(
        self,
        grn_item,
        exclude_return_id=None,
    ):
        queryset = SupplierReturnItem.objects.filter(
            grn_item=grn_item,
            supplier_return__status__in=[
                "PENDING_APPROVAL",
                "APPROVED",
                "CREDIT_ISSUED",
            ],
        )

        if exclude_return_id:
            queryset = queryset.exclude(
                supplier_return_id=exclude_return_id,
            )

        return int(queryset.aggregate(total=Sum("quantity"))["total"] or 0)

    def get_available_quantity(self, obj):
        if not obj.grn_item_id:
            return 0

        accepted = int(
            obj.grn_item.accepted_quantity or obj.grn_item.received_quantity or 0
        )

        already_returned = self._already_returned(
            obj.grn_item,
            exclude_return_id=obj.supplier_return_id,
        )

        return max(0, accepted - already_returned)

    def validate(self, attrs):
        grn_item = attrs.get(
            "grn_item",
            getattr(self.instance, "grn_item", None),
        )
        product = attrs.get(
            "product",
            getattr(self.instance, "product", None),
        )
        variant = attrs.get(
            "variant",
            getattr(self.instance, "variant", None),
        )

        quantity = int(
            attrs.get(
                "quantity",
                getattr(self.instance, "quantity", 0),
            )
            or 0
        )

        unit_price = Decimal(
            str(
                attrs.get(
                    "unit_price",
                    getattr(self.instance, "unit_price", 0),
                )
                or 0
            )
        )

        tax_treatment = str(
            attrs.get(
                "tax_treatment",
                getattr(
                    self.instance,
                    "tax_treatment",
                    "STANDARD_VAT",
                ),
            )
            or "STANDARD_VAT"
        ).upper()

        if tax_treatment in {
            "ZERO_RATED",
            "ZERO_VAT",
        }:
            tax_treatment = "ZERO_VAT"
        elif tax_treatment in {
            "EXEMPT",
            "NON_TAXABLE",
            "NON_VAT",
            "OUT_OF_SCOPE",
        }:
            tax_treatment = "NON_VAT"
        else:
            tax_treatment = "STANDARD_VAT"

        vat_percentage = Decimal(
            str(
                attrs.get(
                    "vat_percentage",
                    getattr(self.instance, "vat_percentage", 0),
                )
                or 0
            )
        )

        errors = {}

        if not grn_item:
            errors["grn_item"] = "GRN item is required."

        if not product:
            errors["product"] = "Product is required."

        if grn_item and product and grn_item.product_id != product.id:
            errors["product"] = "Product must match the selected GRN item."

        if grn_item:
            grn_variant_id = grn_item.variant_id
            variant_id = variant.id if variant else None

            if grn_variant_id != variant_id:
                errors["variant"] = "Variant must match the selected GRN item."

            accepted = int(
                grn_item.accepted_quantity or grn_item.received_quantity or 0
            )

            exclude_return_id = (
                self.instance.supplier_return_id
                if self.instance
                else self.context.get("supplier_return_id")
            )

            returned = self._already_returned(
                grn_item,
                exclude_return_id=exclude_return_id,
            )

            available = max(0, accepted - returned)

            if quantity > available:
                errors["quantity"] = (
                    "Return quantity cannot exceed the remaining "
                    f"returnable quantity ({available})."
                )

            attrs["received_quantity"] = accepted

        if quantity <= 0:
            errors["quantity"] = "Return quantity must be greater than zero."

        if unit_price < 0:
            errors["unit_price"] = "Unit price cannot be negative."

        if vat_percentage < 0:
            errors["vat_percentage"] = "VAT percentage cannot be negative."

        if tax_treatment != "STANDARD_VAT":
            vat_percentage = Decimal("0")

        if errors:
            raise serializers.ValidationError(errors)

        net_amount = Decimal(quantity) * unit_price
        vat_amount = net_amount * vat_percentage / Decimal("100")

        attrs["quantity"] = quantity
        attrs["unit_price"] = unit_price
        attrs["tax_treatment"] = tax_treatment
        attrs["vat_percentage"] = vat_percentage
        attrs["vat_amount"] = vat_amount
        attrs["line_total"] = net_amount + vat_amount

        return attrs


class SupplierReturnSerializer(serializers.ModelSerializer):
    return_number = serializers.CharField(
        read_only=True,
    )

    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    vat_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    total_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    items = SupplierReturnItemSerializer(
        many=True,
        required=True,
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
            "return_number",
            "subtotal",
            "vat_amount",
            "total_amount",
            "approved_at",
            "approved_by",
            "submitted_at",
            "vendor_credit",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

        extra_kwargs = {
            "return_number": {
                "required": False,
            },
            "subtotal": {
                "required": False,
            },
            "vat_amount": {
                "required": False,
            },
            "total_amount": {
                "required": False,
            },
        }

    def _generate_number(self):
        prefix = timezone.localdate().strftime(
            "RTN-%Y%m-",
        )

        last_number = (
            SupplierReturn.objects.select_for_update()
            .filter(
                return_number__startswith=prefix,
            )
            .order_by("-return_number")
            .values_list(
                "return_number",
                flat=True,
            )
            .first()
        )

        sequence = 1

        if last_number:
            try:
                sequence = (
                    int(
                        last_number.rsplit(
                            "-",
                            1,
                        )[-1]
                    )
                    + 1
                )
            except (TypeError, ValueError):
                sequence = (
                    SupplierReturn.objects.filter(
                        return_number__startswith=prefix,
                    ).count()
                    + 1
                )

        candidate = f"{prefix}{sequence:04d}"

        while SupplierReturn.objects.filter(
            return_number=candidate,
        ).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"

        return candidate

    def _normalize_tax_treatment(self, value):
        treatment = str(value or "STANDARD_VAT").strip().upper()

        if treatment in {
            "ZERO_VAT",
            "ZERO_RATED",
            "ZERO-RATED",
        }:
            return "ZERO_VAT"

        if treatment in {
            "NON_VAT",
            "NON-VAT",
            "OUT_OF_SCOPE",
            "EXEMPT",
            "VAT_EXEMPT",
            "NON_TAXABLE",
        }:
            return "NON_VAT"

        return "STANDARD_VAT"

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

        errors = {}

        if not grn:
            errors["grn"] = "A confirmed GRN is required."
        elif not grn.is_confirmed:
            errors["grn"] = "Only a confirmed GRN can be returned."

        if grn and supplier and supplier.id != grn.supplier_id:
            errors["supplier"] = "Supplier must match the selected GRN."

        if grn and branch and branch.id != grn.branch_id:
            errors["branch"] = "Branch must match the selected GRN."

        if grn:
            if not supplier:
                attrs["supplier"] = grn.supplier

            if not branch:
                attrs["branch"] = grn.branch

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def _get_po_item(self, grn, grn_item):
        return (
            grn.purchase_order.items.filter(
                product_id=grn_item.product_id,
                variant_id=grn_item.variant_id,
            )
            .order_by("id")
            .first()
        )

    def _validate_items(
        self,
        grn,
        items,
    ):
        grn_items = {
            item.id: item
            for item in grn.items.select_related(
                "product",
                "variant",
            ).all()
        }

        for item in items:
            grn_item = item.get("grn_item")

            if not grn_item or grn_item.id not in grn_items:
                raise serializers.ValidationError(
                    {"items": ("Each return item must belong " "to the selected GRN.")}
                )

            source = grn_items[grn_item.id]

            product = item.get("product")

            if not product or product.id != source.product_id:
                raise serializers.ValidationError(
                    {"items": ("Return product does not match " "the GRN item.")}
                )

            variant = item.get("variant")
            variant_id = variant.id if variant else None

            if variant_id != source.variant_id:
                raise serializers.ValidationError(
                    {"items": ("Return variant does not match " "the GRN item.")}
                )

            previously_returned = int(
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
                .aggregate(
                    total=Sum("quantity"),
                )["total"]
                or 0
            )

            accepted_quantity = int(
                source.accepted_quantity or source.received_quantity or 0
            )

            available_quantity = max(
                0,
                accepted_quantity - previously_returned,
            )

            quantity = int(
                item.get(
                    "quantity",
                    0,
                )
                or 0
            )

            if quantity <= 0:
                raise serializers.ValidationError(
                    {"items": ("Return quantity must be greater " "than zero.")}
                )

            if quantity > available_quantity:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Return quantity for {source.product} "
                            f"exceeds the available quantity of "
                            f"{available_quantity}."
                        )
                    }
                )

            po_item = self._get_po_item(
                grn,
                source,
            )

            source_tax_treatment = self._normalize_tax_treatment(
                getattr(
                    po_item,
                    "tax_treatment",
                    getattr(
                        po_item,
                        "vat_treatment",
                        "STANDARD_VAT",
                    ),
                )
                if po_item
                else "STANDARD_VAT"
            )

            source_vat_percentage = Decimal(
                str(
                    getattr(
                        po_item,
                        "vat_percentage",
                        0,
                    )
                    or 0
                )
            )

            if source_tax_treatment != "STANDARD_VAT":
                source_vat_percentage = Decimal("0")

            source_unit_price = Decimal(
                str(
                    getattr(
                        po_item,
                        "unit_price",
                        item.get("unit_price", 0),
                    )
                    or 0
                )
            )

            item["received_quantity"] = accepted_quantity
            item["quantity"] = quantity
            item["unit_price"] = source_unit_price
            item["tax_treatment"] = source_tax_treatment
            item["vat_percentage"] = source_vat_percentage

    def _calculate_item_values(
        self,
        item,
    ):
        quantity = int(
            item.get(
                "quantity",
                0,
            )
            or 0
        )

        unit_price = Decimal(
            str(
                item.get(
                    "unit_price",
                    0,
                )
                or 0
            )
        )

        tax_treatment = self._normalize_tax_treatment(
            item.get(
                "tax_treatment",
                "STANDARD_VAT",
            )
        )

        vat_percentage = Decimal(
            str(
                item.get(
                    "vat_percentage",
                    0,
                )
                or 0
            )
        )

        if tax_treatment != "STANDARD_VAT":
            vat_percentage = Decimal("0")

        net_amount = Decimal(quantity) * unit_price

        item_vat_amount = net_amount * vat_percentage / Decimal("100")

        line_total = net_amount + item_vat_amount

        return {
            "received_quantity": int(
                item.get(
                    "received_quantity",
                    quantity,
                )
                or quantity
            ),
            "quantity": quantity,
            "unit_price": unit_price,
            "tax_treatment": tax_treatment,
            "vat_percentage": vat_percentage,
            "vat_amount": item_vat_amount,
            "net_amount": net_amount,
            "line_total": line_total,
        }

    def _save_items(
        self,
        supplier_return,
        items,
    ):
        supplier_return.items.all().delete()

        subtotal = Decimal("0.00")
        vat_amount = Decimal("0.00")
        total_amount = Decimal("0.00")

        for source_item in items:
            item = dict(source_item)

            for field in (
                "id",
                "supplier_return",
                "available_quantity",
                "product_name",
                "sku",
            ):
                item.pop(
                    field,
                    None,
                )

            values = self._calculate_item_values(
                item,
            )

            SupplierReturnItem.objects.create(
                supplier_return=supplier_return,
                grn_item=item["grn_item"],
                product=item["product"],
                variant=item.get("variant"),
                received_quantity=values["received_quantity"],
                quantity=values["quantity"],
                unit_price=values["unit_price"],
                tax_treatment=values["tax_treatment"],
                vat_percentage=values["vat_percentage"],
                vat_amount=values["vat_amount"],
                line_total=values["line_total"],
                reason=item.get(
                    "reason",
                    "",
                ),
            )

            subtotal += values["net_amount"]
            vat_amount += values["vat_amount"]
            total_amount += values["line_total"]

        supplier_return.subtotal = subtotal
        supplier_return.vat_amount = vat_amount
        supplier_return.total_amount = total_amount

        supplier_return.save(
            update_fields=[
                "subtotal",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
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
                {"items": ("Select at least one item " "to return.")}
            )

        grn = validated_data.get("grn")

        if not grn:
            raise serializers.ValidationError({"grn": ("A confirmed GRN is required.")})

        self._validate_items(
            grn,
            items,
        )

        validated_data.pop(
            "return_number",
            None,
        )

        validated_data.pop(
            "subtotal",
            None,
        )

        validated_data.pop(
            "vat_amount",
            None,
        )

        validated_data.pop(
            "total_amount",
            None,
        )

        validated_data["return_number"] = self._generate_number()

        validated_data["subtotal"] = Decimal("0.00")
        validated_data["vat_amount"] = Decimal("0.00")
        validated_data["total_amount"] = Decimal("0.00")

        if validated_data.get("status") == "PENDING_APPROVAL":
            validated_data["submitted_at"] = timezone.now()

        supplier_return = SupplierReturn.objects.create(**validated_data)

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
        if instance.status in {
            "APPROVED",
            "CREDIT_ISSUED",
            "CANCELLED",
        }:
            raise serializers.ValidationError(
                ("Approved, credited, or cancelled " "returns cannot be edited.")
            )

        items = validated_data.pop(
            "items",
            None,
        )

        validated_data.pop(
            "return_number",
            None,
        )

        validated_data.pop(
            "subtotal",
            None,
        )

        validated_data.pop(
            "vat_amount",
            None,
        )

        validated_data.pop(
            "total_amount",
            None,
        )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("Select at least one item " "to return.")}
                )

            grn = validated_data.get(
                "grn",
                instance.grn,
            )

            self._validate_items(
                grn,
                items,
            )

        if (
            validated_data.get("status") == "PENDING_APPROVAL"
            and not instance.submitted_at
        ):
            validated_data["submitted_at"] = timezone.now()

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

    def validate(self, attrs):
        treatment = str(
            attrs.get(
                "tax_treatment",
                getattr(
                    self.instance,
                    "tax_treatment",
                    "STANDARD_VAT",
                ),
            )
            or "STANDARD_VAT"
        ).upper()

        if treatment in {"ZERO_RATED", "ZERO_VAT"}:
            treatment = "ZERO_VAT"
        elif treatment in {
            "NON_VAT",
            "OUT_OF_SCOPE",
            "EXEMPT",
            "NON_TAXABLE",
        }:
            treatment = "NON_VAT"
        else:
            treatment = "STANDARD_VAT"

        percentage = Decimal(
            str(
                attrs.get(
                    "tax_percentage",
                    getattr(self.instance, "tax_percentage", 0),
                )
                or 0
            )
        )

        if treatment != "STANDARD_VAT":
            percentage = Decimal("0")

        attrs["tax_treatment"] = treatment
        attrs["tax_percentage"] = percentage

        return attrs


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


class VendorCreditSerializer(serializers.ModelSerializer):
    credit_number = serializers.CharField(
        read_only=True,
    )

    items = VendorCreditItemSerializer(
        many=True,
        required=True,
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

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    reason_display = serializers.CharField(
        source="get_reason_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    approved_by_name = serializers.SerializerMethodField()

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = VendorCredit
        fields = "__all__"

        read_only_fields = [
            "credit_number",
            "subtotal",
            "tax_amount",
            "total_amount",
            "applied_amount",
            "remaining_amount",
            "approved_by",
            "approval_date",
            "posted_at",
            "voided_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def get_approved_by_name(self, obj):
        user = obj.approved_by

        if not user:
            return ""

        if hasattr(user, "get_full_name"):
            full_name = (user.get_full_name() or "").strip()

            if full_name:
                return full_name

        return (
            getattr(
                user,
                "display_name",
                None,
            )
            or getattr(
                user,
                "name",
                None,
            )
            or getattr(
                user,
                "email",
                None,
            )
            or getattr(
                user,
                "username",
                None,
            )
            or str(user)
        )

    def _generate_number(self):
        prefix = timezone.localdate().strftime(
            "VC-%Y%m-",
        )

        last_number = (
            VendorCredit.objects.select_for_update()
            .filter(
                credit_number__startswith=prefix,
            )
            .order_by(
                "-credit_number",
            )
            .values_list(
                "credit_number",
                flat=True,
            )
            .first()
        )

        sequence = 1

        if last_number:
            try:
                sequence = (
                    int(
                        last_number.rsplit(
                            "-",
                            1,
                        )[-1]
                    )
                    + 1
                )
            except (
                TypeError,
                ValueError,
            ):
                sequence = (
                    VendorCredit.objects.filter(
                        credit_number__startswith=prefix,
                    ).count()
                    + 1
                )

        candidate = f"{prefix}{sequence:04d}"

        while VendorCredit.objects.filter(
            credit_number=candidate,
        ).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"

        return candidate

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
                or 0
            )
        )

        unit_price = Decimal(
            str(
                item.get(
                    "unit_price",
                    0,
                )
                or 0
            )
        )

        tax_treatment = str(
            item.get(
                "tax_treatment",
                "STANDARD_VAT",
            )
            or "STANDARD_VAT"
        ).upper()

        if tax_treatment in {"ZERO_RATED", "ZERO_VAT"}:
            tax_treatment = "ZERO_VAT"
        elif tax_treatment in {
            "NON_VAT",
            "OUT_OF_SCOPE",
            "EXEMPT",
            "NON_TAXABLE",
        }:
            tax_treatment = "NON_VAT"
        else:
            tax_treatment = "STANDARD_VAT"

        tax_percentage = Decimal(
            str(
                item.get(
                    "tax_percentage",
                    0,
                )
                or 0
            )
        )

        if tax_treatment != "STANDARD_VAT":
            tax_percentage = Decimal("0")

        item["tax_treatment"] = tax_treatment
        item["tax_percentage"] = tax_percentage

        if quantity <= 0:
            raise serializers.ValidationError(
                {"items": ("Item quantity must be " "greater than zero.")}
            )

        if unit_price < 0:
            raise serializers.ValidationError(
                {"items": ("Item unit price cannot " "be negative.")}
            )

        if tax_percentage < 0:
            raise serializers.ValidationError(
                {"items": ("Item tax percentage cannot " "be negative.")}
            )

        subtotal = quantity * unit_price

        tax_amount = subtotal * tax_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "line_total": (subtotal + tax_amount),
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

        errors = {}

        if not supplier_return:
            errors["supplier_return"] = "An approved Supplier Return is required."
        elif supplier_return.status not in {
            "APPROVED",
            "CREDIT_ISSUED",
        }:
            errors["supplier_return"] = (
                "Only an approved Supplier Return can create a Vendor Credit."
            )

        if supplier_return:
            existing_credit = VendorCredit.objects.filter(
                supplier_return=supplier_return,
            )

            if self.instance:
                existing_credit = existing_credit.exclude(
                    pk=self.instance.pk,
                )

            if existing_credit.exists():
                errors["supplier_return"] = (
                    "This Supplier Return is already linked to another "
                    "Vendor Credit."
                )

            if not supplier:
                attrs["supplier"] = supplier_return.supplier
                supplier = supplier_return.supplier

            if not branch:
                attrs["branch"] = supplier_return.branch
                branch = supplier_return.branch

            if not purchase_order:
                attrs["purchase_order"] = supplier_return.grn.purchase_order
                purchase_order = supplier_return.grn.purchase_order

        if not supplier:
            errors["supplier"] = "Vendor is required."

        if supplier_return and supplier and supplier_return.supplier_id != supplier.id:
            errors["supplier_return"] = "Return must belong to " "the selected vendor."

        if purchase_order and supplier and purchase_order.supplier_id != supplier.id:
            errors["purchase_order"] = (
                "Purchase order must belong to " "the selected vendor."
            )

        if supplier_bill and supplier and supplier_bill.supplier_id != supplier.id:
            errors["supplier_bill"] = "Bill must belong to " "the selected vendor."

        if supplier_return and branch and supplier_return.branch_id != branch.id:
            errors["branch"] = "Branch must match the linked " "supplier return."

        if purchase_order and branch and purchase_order.branch_id != branch.id:
            errors["branch"] = "Branch must match the linked " "purchase order."

        if supplier_bill and branch and supplier_bill.branch_id != branch.id:
            errors["branch"] = "Branch must match the linked " "supplier bill."

        if errors:
            raise serializers.ValidationError(errors)

        # Approval must go through VendorCreditViewSet.post() or
        # update-status. Prevent the edit form from directly posting it.
        if not self.instance:
            attrs["status"] = "DRAFT"
        elif self.instance.status != "DRAFT":
            attrs.pop("status", None)

        return attrs

    def _validate_applications(
        self,
        supplier,
        applications,
        total_credit,
    ):
        applied_total = Decimal("0.00")
        seen = set()

        for application in applications:
            bill = application.get("bill")

            if not bill:
                raise serializers.ValidationError(
                    {
                        "applications": (
                            "Select a supplier bill " "for every application."
                        )
                    }
                )

            amount = Decimal(
                str(
                    application.get(
                        "amount",
                        0,
                    )
                    or 0
                )
            )

            if bill.id in seen:
                raise serializers.ValidationError(
                    {"applications": ("A bill cannot be selected " "more than once.")}
                )

            seen.add(bill.id)

            if supplier and bill.supplier_id != supplier.id:
                raise serializers.ValidationError(
                    {
                        "applications": (
                            "Every bill must belong to " "the selected vendor."
                        )
                    }
                )

            if amount < 0:
                raise serializers.ValidationError(
                    {"applications": ("Applied amount cannot " "be negative.")}
                )

            current_balance = Decimal(str(bill.balance_due or 0))

            if amount > current_balance:
                raise serializers.ValidationError(
                    {
                        "applications": (
                            f"Application exceeds the open "
                            f"balance of {bill.bill_number}."
                        )
                    }
                )

            applied_total += amount

        if applied_total > total_credit:
            raise serializers.ValidationError(
                {"applications": ("Applied amount cannot exceed " "the total credit.")}
            )

        return applied_total

    def _save_items(
        self,
        vendor_credit,
        items,
    ):
        vendor_credit.items.all().delete()

        for source_item in items:
            item = dict(source_item)

            item.pop(
                "id",
                None,
            )
            item.pop(
                "vendor_credit",
                None,
            )
            item.pop(
                "tax_amount",
                None,
            )
            item.pop(
                "line_total",
                None,
            )

            values = self._calculate_item(item)

            VendorCreditItem.objects.create(
                vendor_credit=vendor_credit,
                tax_amount=(values["tax_amount"]),
                line_total=(values["line_total"]),
                **item,
            )

    def _save_applications(
        self,
        vendor_credit,
        applications,
    ):
        """
        Store planned applications only.

        Supplier bill balances must be changed only by VendorCreditViewSet.post().
        The previous implementation changed balances here and post() changed
        them again, causing double application.
        """
        vendor_credit.applications.all().delete()

        for source_application in applications:
            application = dict(source_application)

            application.pop(
                "id",
                None,
            )
            application.pop(
                "vendor_credit",
                None,
            )

            amount = Decimal(
                str(
                    application.get(
                        "amount",
                        0,
                    )
                    or 0
                )
            )

            if amount <= Decimal("0.00"):
                continue

            VendorCreditApplication.objects.create(
                vendor_credit=vendor_credit,
                **application,
            )

    def _calculate_totals(
        self,
        items,
    ):
        subtotal = Decimal("0.00")
        tax_amount = Decimal("0.00")
        total_amount = Decimal("0.00")

        for item in items:
            values = self._calculate_item(item)

            subtotal += values["subtotal"]
            tax_amount += values["tax_amount"]
            total_amount += values["line_total"]

        return (
            subtotal,
            tax_amount,
            total_amount,
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
                {"items": ("Add at least one vendor " "credit line.")}
            )

        (
            subtotal,
            tax_amount,
            total_amount,
        ) = self._calculate_totals(items)

        self._validate_applications(
            validated_data.get("supplier"),
            applications,
            total_amount,
        )

        validated_data.pop(
            "credit_number",
            None,
        )
        validated_data.pop(
            "subtotal",
            None,
        )
        validated_data.pop(
            "tax_amount",
            None,
        )
        validated_data.pop(
            "total_amount",
            None,
        )
        validated_data.pop(
            "applied_amount",
            None,
        )
        validated_data.pop(
            "remaining_amount",
            None,
        )
        validated_data.pop(
            "approved_by",
            None,
        )
        validated_data.pop(
            "approval_date",
            None,
        )
        validated_data.pop(
            "posted_at",
            None,
        )

        validated_data.update(
            credit_number=(self._generate_number()),
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            applied_amount=Decimal("0.00"),
            remaining_amount=(total_amount),
            status="DRAFT",
        )

        vendor_credit = VendorCredit.objects.create(**validated_data)

        self._save_items(
            vendor_credit,
            items,
        )

        self._save_applications(
            vendor_credit,
            applications,
        )

        if vendor_credit.supplier_return_id:
            supplier_return = vendor_credit.supplier_return

            if supplier_return.vendor_credit_id != vendor_credit.id:
                supplier_return.vendor_credit = vendor_credit
                supplier_return.save(
                    update_fields=[
                        "vendor_credit",
                        "updated_at",
                    ]
                )

        return vendor_credit

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        if instance.status != "DRAFT":
            raise serializers.ValidationError(
                {"status": ("Only draft vendor credits " "can be edited.")}
            )

        items = validated_data.pop(
            "items",
            None,
        )

        applications = validated_data.pop(
            "applications",
            None,
        )

        validated_data.pop(
            "credit_number",
            None,
        )
        validated_data.pop(
            "subtotal",
            None,
        )
        validated_data.pop(
            "tax_amount",
            None,
        )
        validated_data.pop(
            "total_amount",
            None,
        )
        validated_data.pop(
            "applied_amount",
            None,
        )
        validated_data.pop(
            "remaining_amount",
            None,
        )
        validated_data.pop(
            "approved_by",
            None,
        )
        validated_data.pop(
            "approval_date",
            None,
        )
        validated_data.pop(
            "posted_at",
            None,
        )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("Add at least one vendor " "credit line.")}
                )

            (
                subtotal,
                tax_amount,
                total_amount,
            ) = self._calculate_totals(items)

            validated_data.update(
                subtotal=subtotal,
                tax_amount=tax_amount,
                total_amount=total_amount,
                remaining_amount=(total_amount),
                applied_amount=Decimal("0.00"),
            )
        else:
            total_amount = Decimal(str(instance.total_amount or 0))

        if applications is not None:
            self._validate_applications(
                validated_data.get(
                    "supplier",
                    instance.supplier,
                ),
                applications,
                total_amount,
            )

        validated_data["status"] = "DRAFT"

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
    expense_number = serializers.CharField(read_only=True)
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
