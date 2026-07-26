from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from .models import *
from apps.inventory.models import ProductStock, StockMovement


def calc(item, q="quantity"):
    qty = Decimal(str(item.get(q, 0) or 0))
    price = Decimal(str(item.get("unit_price", 0) or 0))
    vat = Decimal(str(item.get("vat_percentage", 0) or 0))
    base = qty * price
    return base, base * vat / Decimal("100"), base + (base * vat / Decimal("100"))


class LineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)

    class Meta:
        fields = "__all__"


class QuotationItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    product_sku = serializers.CharField(
        source="product.sku",
        read_only=True,
        allow_null=True,
    )

    variant_name = serializers.SerializerMethodField()

    class Meta:
        model = QuotationItem
        exclude = ["quotation"]

        read_only_fields = [
            "line_total",
        ]

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "variant_name", None)
            or getattr(obj.variant, "name", None)
            or str(obj.variant)
        )


class QuotationSerializer(serializers.ModelSerializer):
    items = QuotationItemSerializer(
        many=True,
    )

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    salesperson_name = serializers.SerializerMethodField()

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = Quotation
        fields = "__all__"

        read_only_fields = [
            "quote_number",
            "sent_at",
            "accepted_at",
            "rejected_at",
            "converted_at",
            "created_at",
            "updated_at",
        ]

    def get_salesperson_name(self, obj):
        if not obj.salesperson:
            return ""

        return obj.salesperson.get_full_name() or obj.salesperson.username

    def _generate_number(self, branch):
        branch_code = (
            getattr(branch, "branch_code", None)
            or getattr(branch, "code", None)
            or "QT"
        )

        prefix = timezone.now().strftime(f"QT-{branch_code}-%Y%m")

        count = Quotation.objects.filter(
            quote_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_line(self, item):
        quantity = Decimal(str(item.get("quantity", 0) or 0))

        unit_price = Decimal(str(item.get("unit_price", 0) or 0))

        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        subtotal = quantity * unit_price
        vat_amount = subtotal * vat_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "line_total": subtotal + vat_amount,
        }

    def validate(self, attrs):
        quote_date = attrs.get(
            "quote_date",
            getattr(self.instance, "quote_date", None),
        )

        valid_until = attrs.get(
            "valid_until",
            getattr(self.instance, "valid_until", None),
        )

        customer = attrs.get(
            "customer",
            getattr(self.instance, "customer", None),
        )

        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        items = attrs.get("items")

        if not customer:
            raise serializers.ValidationError({"customer": "Customer is required."})

        if not branch:
            raise serializers.ValidationError({"branch": "Branch is required."})

        if not quote_date:
            raise serializers.ValidationError({"quote_date": "Quote date is required."})

        if not valid_until:
            raise serializers.ValidationError(
                {"valid_until": "Valid-until date is required."}
            )

        if quote_date and valid_until and valid_until < quote_date:
            raise serializers.ValidationError(
                {"valid_until": "Valid-until date cannot be before quote date."}
            )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Add at least one quotation item."}
                )

            for index, item in enumerate(items, start=1):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: product is required."}
                    )

                quantity = Decimal(str(item.get("quantity", 0) or 0))

                price = Decimal(str(item.get("unit_price", 0) or 0))

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: quantity must be greater than zero."}
                    )

                if price < 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: unit price cannot be negative."}
                    )

        return attrs

    def _save_items(self, quotation, items):
        quotation.items.all().delete()

        for item in items:
            item.pop("id", None)

            calculated = self._calculate_line(item)

            QuotationItem.objects.create(
                quotation=quotation,
                line_total=calculated["line_total"],
                **item,
            )

    def _calculate_totals(self, items, data, instance=None):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        for item in items:
            calculated = self._calculate_line(item)
            subtotal += calculated["subtotal"]
            vat_amount += calculated["vat_amount"]

        shipping = Decimal(
            str(
                data.get(
                    "shipping_amount",
                    getattr(instance, "shipping_amount", 0) or 0,
                )
                or 0
            )
        )

        discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    getattr(instance, "discount_amount", 0) or 0,
                )
                or 0
            )
        )

        total = max(
            Decimal("0"),
            subtotal + vat_amount + shipping - discount,
        )

        return subtotal, vat_amount, total

    def _set_status_timestamps(self, data, instance=None):
        status_value = data.get(
            "status",
            getattr(instance, "status", "DRAFT"),
        )

        previous_status = getattr(instance, "status", None) if instance else None

        if status_value == "SENT" and previous_status != "SENT":
            data["sent_at"] = timezone.now()

        if status_value == "ACCEPTED" and previous_status != "ACCEPTED":
            data["accepted_at"] = timezone.now()

        if status_value == "REJECTED" and previous_status != "REJECTED":
            data["rejected_at"] = timezone.now()

        return data

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("quote_number"):
            validated_data["quote_number"] = self._generate_number(
                validated_data["branch"]
            )

        subtotal, vat_amount, total = self._calculate_totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total,
        )

        self._set_status_timestamps(validated_data)

        quotation = Quotation.objects.create(**validated_data)

        self._save_items(quotation, items)

        return quotation

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)

        if items is not None:
            subtotal, vat_amount, total = self._calculate_totals(
                items,
                validated_data,
                instance,
            )

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total,
            )

        self._set_status_timestamps(
            validated_data,
            instance,
        )

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(instance, items)

        return instance


class SalesOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    product_sku = serializers.CharField(
        source="product.sku",
        read_only=True,
        allow_null=True,
    )

    variant_name = serializers.SerializerMethodField()

    available_stock = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrderItem
        exclude = ["sales_order"]

        read_only_fields = [
            "line_total",
            "fulfilled_quantity",
        ]

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "variant_name", None)
            or getattr(obj.variant, "name", None)
            or str(obj.variant)
        )

    def get_available_stock(self, obj):
        branch = getattr(obj.sales_order, "branch", None)

        if not branch or not obj.product:
            return 0

        stock = ProductStock.objects.filter(
            product=obj.product,
            variant=obj.variant,
            branch=branch,
        ).first()

        if not stock:
            return 0

        return stock.current_stock - stock.reserved_stock - stock.damaged_stock


class SalesOrderSerializer(serializers.ModelSerializer):
    items = SalesOrderItemSerializer(
        many=True,
    )

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    quotation_number = serializers.CharField(
        source="quotation.quote_number",
        read_only=True,
        allow_null=True,
    )

    salesperson_name = serializers.SerializerMethodField()

    delivery_method_display = serializers.CharField(
        source="get_delivery_method_display",
        read_only=True,
    )

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = SalesOrder
        fields = "__all__"

        read_only_fields = [
            "confirmed_at",
            "fulfilled_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]

    def get_salesperson_name(self, obj):
        if not obj.salesperson:
            return ""

        return obj.salesperson.get_full_name() or obj.salesperson.username

    def _generate_number(self, branch):
        branch_code = (
            getattr(branch, "branch_code", None)
            or getattr(branch, "code", None)
            or "SO"
        )

        prefix = timezone.now().strftime(f"SO-{branch_code}-%Y%m")

        count = SalesOrder.objects.filter(
            order_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_line(self, item):
        quantity = Decimal(str(item.get("quantity", 0) or 0))

        unit_price = Decimal(str(item.get("unit_price", 0) or 0))

        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        subtotal = quantity * unit_price
        vat_amount = subtotal * vat_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "line_total": subtotal + vat_amount,
        }

    def _available_stock(self, branch, item):
        stock = ProductStock.objects.filter(
            product=item["product"],
            variant=item.get("variant"),
            branch=branch,
        ).first()

        if not stock:
            return Decimal("0")

        return stock.current_stock - stock.reserved_stock - stock.damaged_stock

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        customer = attrs.get(
            "customer",
            getattr(self.instance, "customer", None),
        )

        order_date = attrs.get(
            "order_date",
            getattr(self.instance, "order_date", None),
        )

        delivery_date = attrs.get(
            "delivery_date",
            getattr(self.instance, "delivery_date", None),
        )

        shipping_address = attrs.get(
            "shipping_address",
            getattr(self.instance, "shipping_address", None),
        )

        quotation = attrs.get(
            "quotation",
            getattr(self.instance, "quotation", None),
        )

        items = attrs.get("items")

        if not branch:
            raise serializers.ValidationError({"branch": "Branch is required."})

        if not customer:
            raise serializers.ValidationError({"customer": "Customer is required."})

        if not order_date:
            raise serializers.ValidationError({"order_date": "Order date is required."})

        if not delivery_date:
            raise serializers.ValidationError(
                {"delivery_date": "Delivery date is required."}
            )

        if delivery_date < order_date:
            raise serializers.ValidationError(
                {"delivery_date": "Delivery date cannot be before order date."}
            )

        if not shipping_address:
            raise serializers.ValidationError(
                {"shipping_address": "Shipping address is required."}
            )

        if quotation:
            if quotation.customer_id != customer.id:
                raise serializers.ValidationError(
                    {
                        "quotation": "Quotation customer does not match the selected customer."
                    }
                )

            if quotation.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "quotation": "Quotation branch does not match the selected branch."
                    }
                )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Add at least one sales order item."}
                )

            for index, item in enumerate(items, start=1):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: product is required."}
                    )

                quantity = Decimal(str(item.get("quantity", 0) or 0))

                unit_price = Decimal(str(item.get("unit_price", 0) or 0))

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: quantity must be greater than zero."}
                    )

                if unit_price < 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: unit price cannot be negative."}
                    )

                available = self._available_stock(
                    branch,
                    item,
                )

                if available < quantity:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: only {available} unit(s) are available."
                        }
                    )

        return attrs

    def _calculate_totals(self, items, data, instance=None):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        for item in items:
            values = self._calculate_line(item)
            subtotal += values["subtotal"]
            vat_amount += values["vat_amount"]

        shipping = Decimal(
            str(
                data.get(
                    "shipping_amount",
                    getattr(instance, "shipping_amount", 0) or 0,
                )
                or 0
            )
        )

        discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    getattr(instance, "discount_amount", 0) or 0,
                )
                or 0
            )
        )

        total = max(
            Decimal("0"),
            subtotal + vat_amount + shipping - discount,
        )

        return subtotal, vat_amount, total

    def _save_items(self, order, items):
        order.items.all().delete()

        for item in items:
            item.pop("id", None)
            values = self._calculate_line(item)

            SalesOrderItem.objects.create(
                sales_order=order,
                line_total=values["line_total"],
                **item,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("order_number"):
            validated_data["order_number"] = self._generate_number(
                validated_data["branch"]
            )

        subtotal, vat_amount, total = self._calculate_totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total,
        )

        order = SalesOrder.objects.create(**validated_data)

        self._save_items(order, items)

        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status in [
            "FULFILLED",
            "CANCELLED",
        ]:
            raise serializers.ValidationError(
                "Fulfilled or cancelled sales orders cannot be edited."
            )

        items = validated_data.pop("items", None)

        if items is not None:
            subtotal, vat_amount, total = self._calculate_totals(
                items,
                validated_data,
                instance,
            )

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total,
            )

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(instance, items)

        return instance


class SalesInvoiceItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    product_sku = serializers.CharField(
        source="product.sku",
        read_only=True,
        allow_null=True,
    )

    variant_name = serializers.SerializerMethodField()

    class Meta:
        model = SalesInvoiceItem
        exclude = ["invoice"]

        read_only_fields = [
            "line_total",
        ]

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "variant_name", None)
            or getattr(obj.variant, "name", None)
            or str(obj.variant)
        )


class SalesInvoiceSerializer(serializers.ModelSerializer):
    items = SalesInvoiceItemSerializer(
        many=True,
    )

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    sales_order_number = serializers.CharField(
        source="sales_order.order_number",
        read_only=True,
        allow_null=True,
    )

    salesperson_name = serializers.SerializerMethodField()

    payment_terms_display = serializers.CharField(
        source="get_payment_terms_display",
        read_only=True,
    )

    bank_account_name = serializers.SerializerMethodField()
    bank_account_iban = serializers.SerializerMethodField()

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = SalesInvoice
        fields = "__all__"

        read_only_fields = [
            "invoice_number",
            "issued_at",
            "paid_at",
            "voided_at",
            "last_reminder_sent_at",
            "created_at",
            "updated_at",
        ]

    def get_salesperson_name(self, obj):
        if not obj.salesperson:
            return ""

        return obj.salesperson.get_full_name() or obj.salesperson.username

    def get_bank_account_name(self, obj):
        if not obj.bank_account:
            return ""

        return getattr(
            obj.bank_account,
            "account_name",
            None,
        ) or str(obj.bank_account)

    def get_bank_account_iban(self, obj):
        if not obj.bank_account:
            return ""

        return getattr(
            obj.bank_account,
            "iban",
            "",
        )

    def _generate_number(self, branch):
        branch_code = (
            getattr(branch, "branch_code", None)
            or getattr(branch, "code", None)
            or "INV"
        )

        prefix = timezone.now().strftime(f"INV-{branch_code}-%Y%m")

        count = SalesInvoice.objects.filter(
            invoice_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_line(self, item):
        quantity = Decimal(str(item.get("quantity", 0) or 0))

        unit_price = Decimal(str(item.get("unit_price", 0) or 0))

        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        subtotal = quantity * unit_price
        vat_amount = subtotal * vat_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "line_total": subtotal + vat_amount,
        }

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        customer = attrs.get(
            "customer",
            getattr(self.instance, "customer", None),
        )

        invoice_date = attrs.get(
            "invoice_date",
            getattr(self.instance, "invoice_date", None),
        )

        due_date = attrs.get(
            "due_date",
            getattr(self.instance, "due_date", None),
        )

        sales_order = attrs.get(
            "sales_order",
            getattr(self.instance, "sales_order", None),
        )

        paid_amount = attrs.get(
            "paid_amount",
            getattr(self.instance, "paid_amount", Decimal("0")),
        )

        items = attrs.get("items")

        if not branch:
            raise serializers.ValidationError({"branch": "Branch is required."})

        if not customer:
            raise serializers.ValidationError({"customer": "Customer is required."})

        if not invoice_date:
            raise serializers.ValidationError(
                {"invoice_date": "Issue date is required."}
            )

        if not due_date:
            raise serializers.ValidationError({"due_date": "Due date is required."})

        if due_date < invoice_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot be before issue date."}
            )

        if sales_order:
            if sales_order.customer_id != customer.id:
                raise serializers.ValidationError(
                    {
                        "sales_order": "Sales Order customer does not match the invoice customer."
                    }
                )

            if sales_order.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "sales_order": "Sales Order branch does not match the invoice branch."
                    }
                )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Add at least one invoice item."}
                )

            for index, item in enumerate(items, start=1):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: product is required."}
                    )

                quantity = Decimal(str(item.get("quantity", 0) or 0))

                unit_price = Decimal(str(item.get("unit_price", 0) or 0))

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: quantity must be greater than zero."}
                    )

                if unit_price < 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: unit price cannot be negative."}
                    )

                order_item = item.get("sales_order_item")

                if order_item:
                    already_invoiced = SalesInvoiceItem.objects.filter(
                        sales_order_item=order_item,
                    ).exclude(invoice=self.instance,).aggregate(value=Sum("quantity"))[
                        "value"
                    ] or Decimal(
                        "0"
                    )

                    remaining = order_item.quantity - already_invoiced

                    if quantity > remaining:
                        raise serializers.ValidationError(
                            {
                                "items": f"Line {index}: only {remaining} unit(s) remain to invoice."
                            }
                        )

        if paid_amount is not None and paid_amount < 0:
            raise serializers.ValidationError(
                {"paid_amount": "Paid amount cannot be negative."}
            )

        return attrs

    def _calculate_totals(
        self,
        items,
        data,
        instance=None,
    ):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        for item in items:
            values = self._calculate_line(item)
            subtotal += values["subtotal"]
            vat_amount += values["vat_amount"]

        shipping = Decimal(
            str(
                data.get(
                    "shipping_amount",
                    getattr(instance, "shipping_amount", 0) or 0,
                )
                or 0
            )
        )

        discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    getattr(instance, "discount_amount", 0) or 0,
                )
                or 0
            )
        )

        total = max(
            Decimal("0"),
            subtotal + vat_amount + shipping - discount,
        )

        paid_amount = Decimal(
            str(
                data.get(
                    "paid_amount",
                    getattr(instance, "paid_amount", 0) or 0,
                )
                or 0
            )
        )

        if paid_amount > total:
            raise serializers.ValidationError(
                {"paid_amount": "Paid amount cannot exceed invoice total."}
            )

        balance = max(
            Decimal("0"),
            total - paid_amount,
        )

        payment_status = (
            "PAID"
            if balance == 0
            else "PARTIALLY_PAID" if paid_amount > 0 else "UNPAID"
        )

        return (
            subtotal,
            vat_amount,
            total,
            balance,
            payment_status,
        )

    def _save_items(self, invoice, items):
        invoice.items.all().delete()

        for item in items:
            item.pop("id", None)
            values = self._calculate_line(item)

            SalesInvoiceItem.objects.create(
                invoice=invoice,
                line_total=values["line_total"],
                **item,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("invoice_number"):
            validated_data["invoice_number"] = self._generate_number(
                validated_data["branch"]
            )

        (
            subtotal,
            vat_amount,
            total,
            balance,
            payment_status,
        ) = self._calculate_totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total,
            balance_due=balance,
            payment_status=payment_status,
            issued_at=timezone.now(),
        )

        if payment_status == "PAID":
            validated_data["paid_at"] = timezone.now()

        invoice = SalesInvoice.objects.create(**validated_data)

        self._save_items(invoice, items)

        return invoice

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.payment_status == "VOID":
            raise serializers.ValidationError("Void invoices cannot be edited.")

        items = validated_data.pop("items", None)

        if items is not None:
            (
                subtotal,
                vat_amount,
                total,
                balance,
                payment_status,
            ) = self._calculate_totals(
                items,
                validated_data,
                instance,
            )

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total,
                balance_due=balance,
                payment_status=payment_status,
            )

            if payment_status == "PAID" and not instance.paid_at:
                validated_data["paid_at"] = timezone.now()

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(instance, items)

        return instance


class POSSaleItemSerializer(LineSerializer):
    class Meta:
        model = POSSaleItem
        exclude = ["sale"]


class POSSaleSerializer(serializers.ModelSerializer):
    items = POSSaleItemSerializer(
        many=True,
    )

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    cashier_name = serializers.SerializerMethodField()

    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )

    class Meta:
        model = POSSale
        fields = "__all__"

        read_only_fields = [
            "receipt_number",
            "completed_at",
            "voided_at",
            "created_at",
            "updated_at",
        ]

    def get_cashier_name(self, obj):
        if not obj.cashier:
            return ""

        return obj.cashier.get_full_name() or obj.cashier.username

    def _generate_number(self, branch):
        branch_code = (
            getattr(branch, "branch_code", None)
            or getattr(branch, "code", None)
            or "POS"
        )

        prefix = timezone.now().strftime(f"POS-{branch_code}-%Y%m")

        count = POSSale.objects.filter(
            receipt_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_line(self, item):
        quantity = Decimal(str(item.get("quantity", 0) or 0))

        unit_price = Decimal(str(item.get("unit_price", 0) or 0))

        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        subtotal = quantity * unit_price
        vat_amount = subtotal * vat_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "line_total": subtotal + vat_amount,
        }

    def _available_stock(self, branch, item):
        stock = ProductStock.objects.filter(
            product=item["product"],
            variant=item.get("variant"),
            branch=branch,
        ).first()

        if not stock:
            return Decimal("0")

        return stock.current_stock - stock.reserved_stock - stock.damaged_stock

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        cashier = attrs.get(
            "cashier",
            getattr(self.instance, "cashier", None),
        )

        items = attrs.get("items")

        if not branch:
            raise serializers.ValidationError({"branch": "Branch is required."})

        if not cashier:
            raise serializers.ValidationError({"cashier": "Cashier is required."})

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Add at least one POS item."}
                )

            for index, item in enumerate(items, start=1):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: product is required."}
                    )

                quantity = Decimal(str(item.get("quantity", 0) or 0))

                unit_price = Decimal(str(item.get("unit_price", 0) or 0))

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: quantity must be greater than zero."}
                    )

                if unit_price < 0:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: unit price cannot be negative."}
                    )

                available = self._available_stock(
                    branch,
                    item,
                )

                if available < quantity:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: only {available} unit(s) are available."
                        }
                    )

        return attrs

    def _calculate_totals(
        self,
        items,
        validated_data,
        instance=None,
    ):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        for item in items:
            values = self._calculate_line(item)
            subtotal += values["subtotal"]
            vat_amount += values["vat_amount"]

        discount = Decimal(
            str(
                validated_data.get(
                    "discount_amount",
                    getattr(instance, "discount_amount", 0) or 0,
                )
                or 0
            )
        )

        total = max(
            Decimal("0"),
            subtotal + vat_amount - discount,
        )

        return subtotal, vat_amount, total

    def _validate_payment(self, data, total):
        method = data.get("payment_method", "CASH")

        if method == "CASH":
            data["cash_amount"] = total
            data["card_amount"] = Decimal("0")

        elif method == "CARD":
            data["card_amount"] = total
            data["cash_amount"] = Decimal("0")

        elif method == "SPLIT":
            cash = Decimal(str(data.get("cash_amount", 0) or 0))
            card = Decimal(str(data.get("card_amount", 0) or 0))

            if cash + card != total:
                raise serializers.ValidationError(
                    {
                        "payment_method": "Cash and card amounts must equal the sale total."
                    }
                )

        return data

    def _save_items(self, sale, items):
        sale.items.all().delete()

        for item in items:
            item.pop("id", None)
            values = self._calculate_line(item)

            POSSaleItem.objects.create(
                sale=sale,
                line_total=values["line_total"],
                **item,
            )

    def _deduct_stock(self, sale):
        for item in sale.items.select_related(
            "product",
            "variant",
        ):
            stock = ProductStock.objects.select_for_update().get(
                product=item.product,
                variant=item.variant,
                branch=sale.branch,
            )

            previous_stock = stock.current_stock
            stock.current_stock = stock.current_stock - item.quantity

            stock.save(
                update_fields=[
                    "current_stock",
                    "updated_at",
                ]
            )

            StockMovement.objects.create(
                movement_number=(f"MOV-{sale.receipt_number}-{item.id}"),
                product=item.product,
                variant=item.variant,
                branch=sale.branch,
                movement_type="SALE",
                quantity=-item.quantity,
                previous_stock=previous_stock,
                new_stock=stock.current_stock,
                reference_type="POS_SALE",
                reference_id=str(sale.id),
                remarks=(f"POS sale {sale.receipt_number}"),
                performed_by=sale.cashier,
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("receipt_number"):
            validated_data["receipt_number"] = self._generate_number(
                validated_data["branch"]
            )

        if not validated_data.get("sale_datetime"):
            validated_data["sale_datetime"] = timezone.now()

        subtotal, vat_amount, total = self._calculate_totals(
            items,
            validated_data,
        )

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total,
            completed_at=timezone.now(),
            status="PAID",
        )

        self._validate_payment(
            validated_data,
            total,
        )

        sale = POSSale.objects.create(**validated_data)

        self._save_items(
            sale,
            items,
        )

        self._deduct_stock(sale)

        return sale

    @transaction.atomic
    def update(self, instance, validated_data):
        raise serializers.ValidationError(
            "Completed POS sales cannot be edited. Void the sale and create a new one."
        )


class SalesCreditNoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    variant_name = serializers.SerializerMethodField()

    already_credited_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = SalesCreditNoteItem
        exclude = ["credit_note"]

        read_only_fields = [
            "line_total",
        ]

    def get_variant_name(self, obj):
        if not obj.variant:
            return ""

        return (
            getattr(obj.variant, "variant_name", None)
            or getattr(obj.variant, "name", None)
            or str(obj.variant)
        )

    def get_already_credited_quantity(self, obj):
        if not obj.invoice_item:
            return 0

        value = SalesCreditNoteItem.objects.filter(
            invoice_item=obj.invoice_item,
            credit_note__status="ISSUED",
        ).exclude(credit_note=obj.credit_note,).aggregate(value=Sum("credit_quantity"))[
            "value"
        ] or Decimal(
            "0"
        )

        return value

    def get_available_quantity(self, obj):
        return max(
            Decimal("0"),
            (obj.invoiced_quantity or Decimal("0"))
            - Decimal(str(self.get_already_credited_quantity(obj))),
        )


class SalesCreditNoteSerializer(serializers.ModelSerializer):
    items = SalesCreditNoteItemSerializer(
        many=True,
    )

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
        allow_null=True,
    )

    linked_return_number = serializers.SerializerMethodField()

    class Meta:
        model = SalesCreditNote
        fields = "__all__"

        read_only_fields = [
            "issued_at",
            "voided_at",
            "created_at",
            "updated_at",
        ]

    def get_linked_return_number(self, obj):
        linked_return = (
            obj.invoice.returns.order_by("-id").first() if obj.invoice else None
        )

        return linked_return.return_number if linked_return else ""

    def _generate_number(self, branch):
        branch_code = (
            getattr(branch, "branch_code", None)
            or getattr(branch, "code", None)
            or "CN"
        )

        prefix = timezone.now().strftime(f"CN-{branch_code}-%Y%m")

        count = SalesCreditNote.objects.filter(
            credit_note_number__startswith=prefix,
        ).count()

        return f"{prefix}-{count + 1:04d}"

    def _calculate_line(self, item):
        quantity = Decimal(str(item.get("credit_quantity", 0) or 0))

        unit_price = Decimal(str(item.get("unit_price", 0) or 0))

        vat_percentage = Decimal(str(item.get("vat_percentage", 0) or 0))

        subtotal = quantity * unit_price
        vat_amount = subtotal * vat_percentage / Decimal("100")

        return {
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "line_total": subtotal + vat_amount,
        }

    def validate(self, attrs):
        invoice = attrs.get(
            "invoice",
            getattr(self.instance, "invoice", None),
        )

        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        customer = attrs.get(
            "customer",
            getattr(self.instance, "customer", None),
        )

        credit_date = attrs.get(
            "credit_date",
            getattr(self.instance, "credit_date", None),
        )

        items = attrs.get("items")

        if not invoice:
            raise serializers.ValidationError(
                {"invoice": "Related invoice is required."}
            )

        if not branch:
            branch = invoice.branch
            attrs["branch"] = branch

        if not customer:
            customer = invoice.customer
            attrs["customer"] = customer

        if invoice.branch_id != branch.id:
            raise serializers.ValidationError(
                {"branch": "Credit-note branch must match the invoice branch."}
            )

        if invoice.customer_id != customer.id:
            raise serializers.ValidationError(
                {"customer": "Credit-note customer must match the invoice customer."}
            )

        if invoice.payment_status == "VOID":
            raise serializers.ValidationError(
                {"invoice": "A void invoice cannot be credited."}
            )

        if not credit_date:
            raise serializers.ValidationError(
                {"credit_date": "Credit-note date is required."}
            )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Select at least one invoice item."}
                )

            for index, item in enumerate(items, start=1):
                invoice_item = item.get("invoice_item")

                if not invoice_item:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: invoice item is required."}
                    )

                if invoice_item.invoice_id != invoice.id:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: item does not belong to the selected invoice."
                        }
                    )

                quantity = Decimal(str(item.get("credit_quantity", 0) or 0))

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: credit quantity must be greater than zero."
                        }
                    )

                already_credited = SalesCreditNoteItem.objects.filter(
                    invoice_item=invoice_item,
                    credit_note__status="ISSUED",
                ).exclude(
                    credit_note=self.instance,
                ).aggregate(
                    value=Sum("credit_quantity")
                )[
                    "value"
                ] or Decimal(
                    "0"
                )

                available = invoice_item.quantity - already_credited

                if quantity > available:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: only {available} unit(s) remain creditable."
                        }
                    )

        return attrs

    def _calculate_totals(self, items):
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        for item in items:
            values = self._calculate_line(item)
            subtotal += values["subtotal"]
            vat_amount += values["vat_amount"]

        return (
            subtotal,
            vat_amount,
            subtotal + vat_amount,
        )

    def _save_items(self, credit_note, items):
        credit_note.items.all().delete()

        for item in items:
            item.pop("id", None)
            values = self._calculate_line(item)

            invoice_item = item.get("invoice_item")

            item.setdefault(
                "product",
                invoice_item.product,
            )

            item.setdefault(
                "variant",
                invoice_item.variant,
            )

            item.setdefault(
                "description",
                invoice_item.description,
            )

            item.setdefault(
                "invoiced_quantity",
                invoice_item.quantity,
            )

            item.setdefault(
                "unit_price",
                invoice_item.unit_price,
            )

            item.setdefault(
                "vat_percentage",
                invoice_item.vat_percentage,
            )

            SalesCreditNoteItem.objects.create(
                credit_note=credit_note,
                line_total=values["line_total"],
                **item,
            )

    def _apply_credit(self, credit_note):
        invoice = credit_note.invoice

        issued_total = invoice.credit_notes.filter(status="ISSUED").aggregate(
            value=Sum("total_amount")
        )["value"] or Decimal("0")

        invoice.balance_due = max(
            Decimal("0"),
            invoice.total_amount - invoice.paid_amount - issued_total,
        )

        if invoice.balance_due == 0:
            invoice.payment_status = "PAID" if invoice.paid_amount > 0 else "UNPAID"

        invoice.save(
            update_fields=[
                "balance_due",
                "payment_status",
                "updated_at",
            ]
        )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("credit_note_number"):
            validated_data["credit_note_number"] = self._generate_number(
                validated_data["branch"]
            )

        subtotal, vat_amount, total = self._calculate_totals(items)

        validated_data.update(
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_amount=total,
        )

        if validated_data.get("status") == "ISSUED":
            validated_data["issued_at"] = timezone.now()

        credit_note = SalesCreditNote.objects.create(**validated_data)

        self._save_items(
            credit_note,
            items,
        )

        if credit_note.status == "ISSUED":
            self._apply_credit(credit_note)

        return credit_note

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status in [
            "VOID",
            "REFUNDED",
        ]:
            raise serializers.ValidationError(
                "Void or fully refunded credit notes cannot be edited."
            )

        previous_status = instance.status
        items = validated_data.pop("items", None)

        if items is not None:
            subtotal, vat_amount, total = self._calculate_totals(items)

            validated_data.update(
                subtotal=subtotal,
                vat_amount=vat_amount,
                total_amount=total,
            )

        if validated_data.get("status") == "ISSUED" and previous_status != "ISSUED":
            validated_data["issued_at"] = timezone.now()

        instance = super().update(
            instance,
            validated_data,
        )

        if items is not None:
            self._save_items(
                instance,
                items,
            )

        if instance.status == "ISSUED" and previous_status != "ISSUED":
            self._apply_credit(instance)

        return instance


class SalesReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = SalesReturnItem
        exclude = ["sales_return"]
        read_only_fields = ["line_total"]


class SalesReturnSerializer(serializers.ModelSerializer):
    items = SalesReturnItemSerializer(many=True)

    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )
    order_number = serializers.CharField(
        source="sales_order.order_number",
        read_only=True,
        allow_null=True,
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = SalesReturn
        fields = "__all__"

    def _generate_number(self):
        prefix = timezone.now().strftime("RTN-%Y%m")
        count = SalesReturn.objects.filter(return_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        order = attrs.get(
            "sales_order",
            getattr(self.instance, "sales_order", None),
        )
        items = attrs.get("items")

        if not order:
            raise serializers.ValidationError(
                {"sales_order": "Related Sales Order is required."}
            )

        attrs["customer"] = order.customer
        attrs["branch"] = order.branch

        if not attrs.get("invoice") and order.invoices.exists():
            attrs["invoice"] = order.invoices.order_by("-id").first()

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": "Select at least one item to return."}
                )

            for index, item in enumerate(items, start=1):
                order_item = item.get("sales_order_item")

                if not order_item:
                    raise serializers.ValidationError(
                        {"items": f"Line {index}: Sales Order item is required."}
                    )
                if order_item.sales_order_id != order.id:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: item does not belong to the selected order."
                        }
                    )

                quantity = Decimal(str(item.get("returned_quantity", 0) or 0))
                already_returned = SalesReturnItem.objects.filter(
                    sales_order_item=order_item,
                ).exclude(
                    sales_return__status__in=[
                        "REJECTED",
                        "CANCELLED",
                    ]
                ).exclude(
                    sales_return=self.instance
                ).aggregate(
                    value=Sum("returned_quantity")
                )[
                    "value"
                ] or Decimal(
                    "0"
                )
                remaining = order_item.quantity - already_returned

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: returned quantity must be greater than zero."
                        }
                    )
                if quantity > remaining:
                    raise serializers.ValidationError(
                        {
                            "items": f"Line {index}: only {remaining} unit(s) remain returnable."
                        }
                    )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        if not validated_data.get("return_number"):
            validated_data["return_number"] = self._generate_number()

        sales_return = SalesReturn.objects.create(**validated_data)
        subtotal = Decimal("0")

        for item in items:
            quantity = Decimal(str(item.get("returned_quantity", 0) or 0))
            price = Decimal(str(item.get("unit_price", 0) or 0))
            line_total = quantity * price
            subtotal += line_total

            SalesReturnItem.objects.create(
                sales_return=sales_return,
                line_total=line_total,
                **item,
            )

        vat = subtotal * Decimal("0.05")
        sales_return.subtotal = subtotal
        sales_return.vat_amount = vat
        sales_return.total_amount = subtotal + vat

        if sales_return.status == "PENDING_APPROVAL":
            sales_return.submitted_at = timezone.now()

        sales_return.save(
            update_fields=[
                "subtotal",
                "vat_amount",
                "total_amount",
                "submitted_at",
                "updated_at",
            ]
        )
        return sales_return


class SalesPaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
        allow_null=True,
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display",
        read_only=True,
    )

    class Meta:
        model = SalesPayment
        fields = "__all__"
        read_only_fields = [
            "cleared_at",
            "reversed_at",
            "created_at",
            "updated_at",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime("PMT-%Y%m")
        count = SalesPayment.objects.filter(payment_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        invoice = attrs.get(
            "invoice",
            getattr(self.instance, "invoice", None),
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
        status_value = attrs.get(
            "status",
            getattr(self.instance, "status", "PAID"),
        )

        if not invoice:
            raise serializers.ValidationError({"invoice": "Invoice is required."})
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Payment amount must be greater than zero."}
            )
        if invoice.payment_status == "VOID":
            raise serializers.ValidationError(
                {"invoice": "Payments cannot be recorded against a void invoice."}
            )
        if amount > (invoice.balance_due or Decimal("0")):
            raise serializers.ValidationError(
                {
                    "amount": f"Payment cannot exceed the remaining balance of {invoice.balance_due}."
                }
            )

        attrs["customer"] = invoice.customer
        attrs["branch"] = invoice.branch
        attrs["currency"] = invoice.currency

        if status_value == "PAID":
            attrs["cleared_at"] = timezone.now()

        return attrs

    def _update_invoice(self, invoice):
        total_paid = invoice.payments.filter(status="PAID").aggregate(
            value=Sum("amount")
        )["value"] or Decimal("0")
        credited = invoice.credit_notes.filter(status="ISSUED").aggregate(
            value=Sum("total_amount")
        )["value"] or Decimal("0")

        invoice.paid_amount = total_paid
        invoice.balance_due = max(
            Decimal("0"),
            (invoice.total_amount or Decimal("0")) - total_paid - credited,
        )

        if invoice.balance_due == 0:
            invoice.payment_status = "PAID"
            invoice.paid_at = timezone.now()
        elif total_paid > 0:
            invoice.payment_status = "PARTIALLY_PAID"
            invoice.paid_at = None
        else:
            invoice.payment_status = "UNPAID"
            invoice.paid_at = None

        invoice.save(
            update_fields=[
                "paid_amount",
                "balance_due",
                "payment_status",
                "paid_at",
                "updated_at",
            ]
        )

    @transaction.atomic
    def create(self, validated_data):
        if not validated_data.get("payment_number"):
            validated_data["payment_number"] = self._generate_number()

        payment = SalesPayment.objects.create(**validated_data)

        if payment.status == "PAID":
            self._update_invoice(payment.invoice)

        return payment


class PriceListItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.product_name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = PriceListItem
        exclude = ["price_list"]


class PriceListSerializer(serializers.ModelSerializer):
    items = PriceListItemSerializer(
        many=True,
        required=False,
    )
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )
    item_count = serializers.IntegerField(
        source="items.count",
        read_only=True,
    )
    applies_to_display = serializers.CharField(
        source="get_applies_to_display",
        read_only=True,
    )
    discount_display = serializers.SerializerMethodField()

    class Meta:
        model = PriceList
        fields = "__all__"

    def get_discount_display(self, obj):
        if obj.discount_type == "PERCENTAGE":
            return f"{obj.discount_percentage}%"
        if obj.discount_type == "FIXED":
            return f"AED {obj.fixed_discount}"
        return "Custom prices"

    def validate(self, attrs):
        valid_from = attrs.get(
            "valid_from",
            getattr(self.instance, "valid_from", None),
        )
        valid_until = attrs.get(
            "valid_until",
            getattr(self.instance, "valid_until", None),
        )

        if valid_from and valid_until and valid_until < valid_from:
            raise serializers.ValidationError(
                {"valid_until": "Valid-until date cannot be before valid-from date."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        customer_ids = validated_data.pop("customer_ids", [])

        price_list = PriceList.objects.create(**validated_data)

        for item in items:
            PriceListItem.objects.create(
                price_list=price_list,
                **item,
            )

        for customer_id in customer_ids:
            PriceListCustomer.objects.get_or_create(
                price_list=price_list,
                customer_id=customer_id,
            )

        return price_list


class SalesReportSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.customer_name",
        read_only=True,
        allow_null=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    report_type_display = serializers.CharField(
        source="get_report_type_display",
        read_only=True,
    )

    period_display = serializers.CharField(
        source="get_period_display",
        read_only=True,
    )

    group_by_display = serializers.CharField(
        source="get_group_by_display",
        read_only=True,
    )

    output_format_display = serializers.CharField(
        source="get_output_format_display",
        read_only=True,
    )

    recurrence_display = serializers.CharField(
        source="get_recurrence_display",
        read_only=True,
    )

    class Meta:
        model = SalesReport
        fields = "__all__"

        read_only_fields = [
            "generated_at",
            "last_run_at",
            "error_message",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        period = attrs.get(
            "period",
            getattr(
                self.instance,
                "period",
                None,
            ),
        )

        custom_start = attrs.get(
            "custom_start",
            getattr(
                self.instance,
                "custom_start",
                None,
            ),
        )

        custom_end = attrs.get(
            "custom_end",
            getattr(
                self.instance,
                "custom_end",
                None,
            ),
        )

        if period == "CUSTOM":
            if not custom_start:
                raise serializers.ValidationError(
                    {"custom_start": "Start date is required for a custom period."}
                )

            if not custom_end:
                raise serializers.ValidationError(
                    {"custom_end": "End date is required for a custom period."}
                )

            if custom_end < custom_start:
                raise serializers.ValidationError(
                    {"custom_end": "End date cannot be before start date."}
                )

        if period != "CUSTOM":
            attrs["custom_start"] = None
            attrs["custom_end"] = None

        return attrs

    def create(self, validated_data):
        recurrence = validated_data.get(
            "recurrence",
            "ONCE",
        )

        validated_data["status"] = "SCHEDULED" if recurrence == "RECURRING" else "READY"

        if recurrence == "ONCE":
            validated_data["generated_at"] = timezone.now()
            validated_data["last_run_at"] = timezone.now()

        return super().create(validated_data)
