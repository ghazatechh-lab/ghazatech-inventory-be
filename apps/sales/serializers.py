from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from .models import *
from apps.inventory.models import ProductStock, StockMovement
from apps.common.sensitive_permissions import has_sensitive_permission
from apps.sales.tax_stock_services import (
    calculate_sales_line,
    deduct_sales_item,
    validate_tax_treatment,
)


def calc(item, q="quantity"):
    qty = Decimal(str(item.get(q, 0) or 0))
    price = Decimal(str(item.get("unit_price", 0) or 0))
    vat = Decimal(str(item.get("vat_percentage", 0) or 0))
    base = qty * price
    return base, base * vat / Decimal("100"), base + (base * vat / Decimal("100"))


class SalesTaxLineSerializerMixin:
    """
    Shared VAT validation for quotation, invoice, POS and credit-note lines.

    `tax_inclusive` is accepted only as a temporary calculation input. It is
    removed before the model row is created because inclusiveness belongs to
    the parent sales document.
    """

    tax_inclusive = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def validate(self, attrs):
        attrs = super().validate(attrs)

        user = self._request_user()
        treatment = str(attrs.get("tax_treatment") or "STANDARD_VAT").strip().upper()
        reason = str(attrs.get("tax_reason") or "").strip()

        try:
            validate_tax_treatment(
                user,
                treatment,
                reason,
            )
        except PermissionError as exc:
            raise serializers.ValidationError({"tax_treatment": str(exc)}) from exc
        except ValueError as exc:
            raise serializers.ValidationError({"tax_treatment": str(exc)}) from exc

        tax_rate = Decimal(
            str(
                attrs.get(
                    "tax_rate",
                    attrs.get("vat_percentage", 5),
                )
                or 0
            )
        )

        if treatment != "STANDARD_VAT":
            tax_rate = Decimal("0.00")

        attrs["tax_treatment"] = treatment
        attrs["tax_reason"] = reason
        attrs["tax_rate"] = tax_rate
        attrs["vat_percentage"] = tax_rate

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self._request_user()

        can_view_sensitive_tax = has_sensitive_permission(
            user,
            "view_non_standard_tax_sale",
        )
        if not can_view_sensitive_tax:
            data.pop("tax_reason", None)

        return data


def calculate_serialized_sales_line(
    item,
    *,
    quantity_key="quantity",
):
    values = calculate_sales_line(
        quantity=item.get(quantity_key, 0),
        unit_price=item.get("unit_price", 0),
        discount=item.get("discount_amount", 0),
        tax_treatment=item.get(
            "tax_treatment",
            "STANDARD_VAT",
        ),
        tax_rate=item.get(
            "tax_rate",
            item.get("vat_percentage", 5),
        ),
        tax_inclusive=bool(item.get("tax_inclusive", False)),
    )

    return {
        "subtotal": values["taxable_amount"],
        "vat_amount": values["tax_amount"],
        "taxable_amount": values["taxable_amount"],
        "tax_amount": values["tax_amount"],
        "line_total": values["line_total"],
    }


class LineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)

    class Meta:
        fields = "__all__"


class QuotationItemSerializer(SalesTaxLineSerializerMixin, serializers.ModelSerializer):
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
            "taxable_amount",
            "tax_amount",
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

    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

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

    def get_updated_by_name(self, obj):
        if not obj.updated_by:
            return ""

        return (
            obj.updated_by.get_full_name()
            or getattr(obj.updated_by, "username", "")
            or getattr(obj.updated_by, "email", "")
            or str(obj.updated_by)
        )

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
        return calculate_serialized_sales_line(
            item,
            quantity_key="quantity",
        )

    def validate(self, attrs):
        # -------------------------------------------------
        # Prevent editing converted/cancelled quotations
        # -------------------------------------------------
        if self.instance:
            current_status = str(self.instance.status or "").upper()

            if current_status in [
                "CONVERTED",
                "CANCELLED",
            ]:
                raise serializers.ValidationError(
                    {
                        "status": (
                            f"{self.instance.get_status_display()} "
                            "quotations cannot be edited."
                        )
                    }
                )

        quote_date = attrs.get(
            "quote_date",
            getattr(
                self.instance,
                "quote_date",
                None,
            ),
        )

        valid_until = attrs.get(
            "valid_until",
            getattr(
                self.instance,
                "valid_until",
                None,
            ),
        )

        customer = attrs.get(
            "customer",
            getattr(
                self.instance,
                "customer",
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

        items = attrs.get("items")

        if not customer:
            raise serializers.ValidationError({"customer": ("Customer is required.")})

        if not branch:
            raise serializers.ValidationError({"branch": ("Branch is required.")})

        if not quote_date:
            raise serializers.ValidationError(
                {"quote_date": ("Quote date is required.")}
            )

        if not valid_until:
            raise serializers.ValidationError(
                {"valid_until": ("Valid-until date is required.")}
            )

        if quote_date and valid_until and valid_until < quote_date:
            raise serializers.ValidationError(
                {"valid_until": ("Valid-until date cannot " "be before quote date.")}
            )

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("Add at least one " "quotation item.")}
                )

            for index, item in enumerate(
                items,
                start=1,
            ):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": (f"Line {index}: " "product is required.")}
                    )

                quantity = Decimal(
                    str(
                        item.get(
                            "quantity",
                            0,
                        )
                        or 0
                    )
                )

                price = Decimal(
                    str(
                        item.get(
                            "unit_price",
                            0,
                        )
                        or 0
                    )
                )

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Line {index}: "
                                "quantity must be "
                                "greater than zero."
                            )
                        }
                    )

                if price < 0:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Line {index}: " "unit price cannot " "be negative."
                            )
                        }
                    )

        return attrs

    def _save_items(
        self,
        quotation,
        items,
    ):
        quotation.items.all().delete()

        for item in items:
            item.pop(
                "id",
                None,
            )

            calculated = self._calculate_line(item)

            item.pop(
                "tax_inclusive",
                None,
            )

            QuotationItem.objects.create(
                quotation=quotation,
                taxable_amount=calculated["taxable_amount"],
                tax_amount=calculated["tax_amount"],
                line_total=calculated["line_total"],
                **item,
            )

    def _calculate_totals(
        self,
        items,
        data,
        instance=None,
    ):
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
                    getattr(
                        instance,
                        "shipping_amount",
                        0,
                    )
                    or 0,
                )
                or 0
            )
        )

        discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    getattr(
                        instance,
                        "discount_amount",
                        0,
                    )
                    or 0,
                )
                or 0
            )
        )

        total = max(
            Decimal("0"),
            subtotal + vat_amount + shipping - discount,
        )

        return (
            subtotal,
            vat_amount,
            total,
        )

    def _set_status_timestamps(
        self,
        data,
        instance=None,
    ):
        status_value = data.get(
            "status",
            getattr(
                instance,
                "status",
                "DRAFT",
            ),
        )

        previous_status = (
            getattr(
                instance,
                "status",
                None,
            )
            if instance
            else None
        )

        if status_value == "SENT" and previous_status != "SENT":
            data["sent_at"] = timezone.now()

        if status_value == "ACCEPTED" and previous_status != "ACCEPTED":
            data["accepted_at"] = timezone.now()

        if status_value == "REJECTED" and previous_status != "REJECTED":
            data["rejected_at"] = timezone.now()

        return data

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        items = validated_data.pop(
            "items",
            [],
        )

        if not validated_data.get("quote_number"):
            validated_data["quote_number"] = self._generate_number(
                validated_data["branch"]
            )

        (
            subtotal,
            vat_amount,
            total,
        ) = self._calculate_totals(
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

        self._save_items(
            quotation,
            items,
        )

        return quotation

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        # Extra safety check
        current_status = str(instance.status or "").upper()

        if current_status in [
            "CONVERTED",
            "CANCELLED",
        ]:
            raise serializers.ValidationError(
                {
                    "status": (
                        f"{instance.get_status_display()} "
                        "quotations cannot be edited."
                    )
                }
            )

        items = validated_data.pop(
            "items",
            None,
        )

        if items is not None:
            (
                subtotal,
                vat_amount,
                total,
            ) = self._calculate_totals(
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
            self._save_items(
                instance,
                items,
            )

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

        return Decimal(str(stock.available_stock or 0))


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
        return calculate_serialized_sales_line(
            item,
            quantity_key="quantity",
        )

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


class SalesInvoiceItemSerializer(
    SalesTaxLineSerializerMixin, serializers.ModelSerializer
):
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
            "subtotal",
            "vat_amount",
            "total_amount",
            "balance_due",
            "payment_status",
            "issued_at",
            "paid_at",
            "voided_at",
            "last_reminder_sent_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return ""

        return (
            obj.created_by.get_full_name()
            or getattr(obj.created_by, "username", "")
            or getattr(obj.created_by, "email", "")
            or str(obj.created_by)
        )

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
        """
        Generate a short invoice number:
        INV-00001, INV-00002, ...

        Existing legacy invoice numbers are left unchanged.
        Only existing short-format invoice numbers are considered
        when determining the next sequence.
        """
        prefix = "INV-"
        highest_sequence = 0

        existing_numbers = SalesInvoice.objects.filter(
            invoice_number__regex=r"^INV-[0-9]{5}$",
        ).values_list(
            "invoice_number",
            flat=True,
        )

        for invoice_number in existing_numbers:
            try:
                sequence = int(str(invoice_number).replace(prefix, "", 1))
            except (TypeError, ValueError):
                continue

            highest_sequence = max(
                highest_sequence,
                sequence,
            )

        return f"{prefix}{highest_sequence + 1:05d}"

    def _calculate_line(self, item):
        return calculate_serialized_sales_line(
            item,
            quantity_key="quantity",
        )

    def validate(self, attrs):
        # --------------------------------------------------
        # Existing paid / void protection
        # --------------------------------------------------

        if self.instance:
            current_payment_status = str(self.instance.payment_status or "").upper()

            if current_payment_status in [
                "PAID",
                "VOID",
            ]:
                raise serializers.ValidationError(
                    {
                        "payment_status": (
                            f"{self.instance.get_payment_status_display()} "
                            "invoices cannot be edited."
                        )
                    }
                )

        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        customer = attrs.get(
            "customer",
            getattr(
                self.instance,
                "customer",
                None,
            ),
        )

        invoice_date = attrs.get(
            "invoice_date",
            getattr(
                self.instance,
                "invoice_date",
                None,
            ),
        )

        due_date = attrs.get(
            "due_date",
            getattr(
                self.instance,
                "due_date",
                None,
            ),
        )

        sales_order = attrs.get(
            "sales_order",
            getattr(
                self.instance,
                "sales_order",
                None,
            ),
        )

        paid_amount = Decimal(
            str(
                attrs.get(
                    "paid_amount",
                    getattr(
                        self.instance,
                        "paid_amount",
                        0,
                    ),
                )
                or 0
            )
        )

        is_historical = bool(
            attrs.get(
                "is_historical",
                getattr(
                    self.instance,
                    "is_historical",
                    False,
                ),
            )
        )

        items = attrs.get("items")

        # --------------------------------------------------
        # Core validation
        # --------------------------------------------------

        if not branch:
            raise serializers.ValidationError({"branch": ("Branch is required.")})

        if not customer:
            raise serializers.ValidationError({"customer": ("Customer is required.")})

        if not invoice_date:
            raise serializers.ValidationError(
                {"invoice_date": ("Issue date is required.")}
            )

        if not due_date:
            raise serializers.ValidationError({"due_date": ("Due date is required.")})

        if due_date and invoice_date and due_date < invoice_date:
            raise serializers.ValidationError(
                {"due_date": ("Due date cannot be before " "issue date.")}
            )

        # --------------------------------------------------
        # Historical invoice rules
        # --------------------------------------------------

        if is_historical:
            if self.instance:
                raise serializers.ValidationError(
                    {
                        "is_historical": (
                            "Historical invoices cannot be edited "
                            "after posting. Use a credit note or "
                            "accounting adjustment instead."
                        )
                    }
                )

            if invoice_date >= timezone.localdate():
                raise serializers.ValidationError(
                    {
                        "invoice_date": (
                            "Previous invoice date must be " "earlier than today."
                        )
                    }
                )

            if sales_order:
                raise serializers.ValidationError(
                    {
                        "sales_order": (
                            "Previous invoices cannot be linked " "to a Sales Order."
                        )
                    }
                )

            if paid_amount > 0:
                raise serializers.ValidationError(
                    {
                        "paid_amount": (
                            "Do not enter payment while importing "
                            "a previous invoice. Save the invoice "
                            "first, then record the historical "
                            "payment using the actual payment date."
                        )
                    }
                )

            attrs["sales_order"] = None
            attrs["sale_type"] = "HISTORICAL"
            attrs["delivery_status"] = "NOT_APPLICABLE"
            attrs["paid_amount"] = Decimal("0.00")

        # --------------------------------------------------
        # Normal Sales Order validation
        # --------------------------------------------------

        elif sales_order:
            if sales_order.customer_id != customer.id:
                raise serializers.ValidationError(
                    {
                        "sales_order": (
                            "Sales Order customer does not "
                            "match the invoice customer."
                        )
                    }
                )

            if sales_order.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "sales_order": (
                            "Sales Order branch does not " "match the invoice branch."
                        )
                    }
                )

        # --------------------------------------------------
        # Item validation
        # --------------------------------------------------

        if items is not None:
            if not items:
                raise serializers.ValidationError(
                    {"items": ("Add at least one invoice item.")}
                )

            for index, item in enumerate(
                items,
                start=1,
            ):
                if not item.get("product"):
                    raise serializers.ValidationError(
                        {"items": (f"Line {index}: " "product is required.")}
                    )

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

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Line {index}: "
                                "quantity must be greater "
                                "than zero."
                            )
                        }
                    )

                if unit_price < 0:
                    raise serializers.ValidationError(
                        {"items": (f"Line {index}: " "unit price cannot be negative.")}
                    )

                order_item = item.get("sales_order_item")

                # Historical invoices must not validate
                # against current order fulfilment.
                if order_item and not is_historical:
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
                                "items": (
                                    f"Line {index}: "
                                    f"only {remaining} "
                                    "unit(s) remain to invoice."
                                )
                            }
                        )

        discount_amount = Decimal(
            str(
                attrs.get(
                    "discount_amount",
                    getattr(self.instance, "discount_amount", 0) or 0,
                )
                or 0
            )
        )

        if discount_amount < 0:
            raise serializers.ValidationError(
                {"discount_amount": "Discount cannot be negative."}
            )

        if items is not None:
            discount_limit = Decimal("0")
            vat_total = Decimal("0")

            for item in items:
                values = self._calculate_line(item)
                discount_limit += values["subtotal"]
                vat_total += values["vat_amount"]

            shipping = Decimal(
                str(
                    attrs.get(
                        "shipping_amount",
                        getattr(self.instance, "shipping_amount", 0) or 0,
                    )
                    or 0
                )
            )
            discount_limit += vat_total + shipping

            if discount_amount > discount_limit:
                raise serializers.ValidationError(
                    {
                        "discount_amount": (
                            "Discount cannot exceed the invoice amount before discount."
                        )
                    }
                )

        if paid_amount is not None and paid_amount < 0:
            raise serializers.ValidationError(
                {"paid_amount": ("Paid amount cannot be negative.")}
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
                    getattr(
                        instance,
                        "shipping_amount",
                        0,
                    )
                    or 0,
                )
                or 0
            )
        )

        discount = Decimal(
            str(
                data.get(
                    "discount_amount",
                    getattr(
                        instance,
                        "discount_amount",
                        0,
                    )
                    or 0,
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
                    getattr(
                        instance,
                        "paid_amount",
                        0,
                    )
                    or 0,
                )
                or 0
            )
        )

        if paid_amount > total:
            raise serializers.ValidationError(
                {"paid_amount": ("Paid amount cannot exceed " "invoice total.")}
            )

        balance = max(
            Decimal("0"),
            total - paid_amount,
        )

        payment_status = (
            "PAID"
            if balance == 0
            else ("PARTIALLY_PAID" if paid_amount > 0 else "UNPAID")
        )

        money_precision = Decimal("0.01")

        return (
            subtotal.quantize(money_precision),
            vat_amount.quantize(money_precision),
            total.quantize(money_precision),
            balance.quantize(money_precision),
            payment_status,
        )

    def _save_items(
        self,
        invoice,
        items,
    ):
        invoice.items.all().delete()

        for item in items:
            item.pop(
                "id",
                None,
            )

            # Historical invoices must not retain
            # SalesOrderItem relationships.
            if invoice.is_historical:
                item["sales_order_item"] = None

            values = self._calculate_line(item)

            item.pop(
                "tax_inclusive",
                None,
            )

            SalesInvoiceItem.objects.create(
                invoice=invoice,
                taxable_amount=values["taxable_amount"],
                tax_amount=values["tax_amount"],
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

        is_historical = bool(
            validated_data.get(
                "is_historical",
                False,
            )
        )

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

        if is_historical:
            validated_data["sales_order"] = None

            validated_data["sale_type"] = "HISTORICAL"

            validated_data["delivery_status"] = "NOT_APPLICABLE"

            validated_data["paid_amount"] = Decimal("0.00")

            balance = total

            payment_status = "UNPAID"

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

        self._save_items(
            invoice,
            items,
        )

        # --------------------------------------------------
        # HISTORICAL ACCOUNTING POSTING
        # --------------------------------------------------

        if is_historical:
            request = self.context.get("request")

            user = getattr(
                request,
                "user",
                None,
            )

            create_and_post_historical_receivable(
                sales_invoice=invoice,
                user=user,
            )

        return invoice

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        # --------------------------------------------------
        # Historical invoices are already accounting-posted.
        # --------------------------------------------------

        if instance.is_historical:
            raise serializers.ValidationError(
                {
                    "is_historical": (
                        "Historical invoices cannot be edited "
                        "after posting. Use a credit note or "
                        "accounting adjustment."
                    )
                }
            )

        # --------------------------------------------------
        # Existing backend protection for payments
        # --------------------------------------------------

        current_payment_status = str(instance.payment_status or "").upper()

        if Decimal(str(instance.paid_amount or 0)) > Decimal("0.00"):
            raise serializers.ValidationError(
                {
                    "payment_status": (
                        "An invoice with recorded payments "
                        "cannot be edited. Reverse the payment "
                        "first, then amend the invoice."
                    )
                }
            )

        if current_payment_status in [
            "PAID",
            "VOID",
        ]:
            raise serializers.ValidationError(
                {
                    "payment_status": (
                        f"{instance.get_payment_status_display()} "
                        "invoices cannot be edited."
                    )
                }
            )

        items = validated_data.pop(
            "items",
            None,
        )

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
            self._save_items(
                instance,
                items,
            )

        return instance


class POSSaleItemSerializer(SalesTaxLineSerializerMixin, LineSerializer):
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
        return calculate_serialized_sales_line(
            item,
            quantity_key="quantity",
        )

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
            item.pop("tax_inclusive", None)

            POSSaleItem.objects.create(
                sale=sale,
                taxable_amount=values["taxable_amount"],
                tax_amount=values["tax_amount"],
                line_total=values["line_total"],
                **item,
            )

    def _deduct_stock(self, sale):
        request = self.context.get("request")

        for item in sale.items.select_related(
            "product",
            "variant",
        ):
            deduct_sales_item(
                item=item,
                branch=sale.branch,
                user=sale.cashier,
                reference_type="POS_SALE",
                reference_id=sale.id,
                request=request,
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
        source="customer.customer_name", read_only=True, allow_null=True
    )
    order_number = serializers.CharField(
        source="sales_order.order_number", read_only=True, allow_null=True
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, allow_null=True
    )

    class Meta:
        model = SalesReturn
        fields = "__all__"
        read_only_fields = [
            "return_number",
            "subtotal",
            "vat_amount",
            "total_amount",
            "submitted_at",
            "approved_at",
            "completed_at",
            "approved_by",
            "approver_name",
            "created_at",
            "updated_at",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime("RTN-%Y%m")
        count = SalesReturn.objects.filter(return_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def _recalculate_totals(self, sales_return):
        subtotal = Decimal("0")

        for item in sales_return.items.all():
            quantity = Decimal(str(item.returned_quantity or 0))
            price = Decimal(str(item.unit_price or 0))
            line_total = quantity * price
            if item.line_total != line_total:
                item.line_total = line_total
                item.save(update_fields=["line_total"])
            subtotal += line_total

        vat = subtotal * Decimal("0.05")
        sales_return.subtotal = subtotal
        sales_return.vat_amount = vat
        sales_return.total_amount = subtotal + vat
        sales_return.save(
            update_fields=[
                "subtotal",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
        )

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

        if self.instance and items is not None:
            if self.instance.status not in ["DRAFT", "REJECTED"]:
                raise serializers.ValidationError(
                    {"status": ("Only Draft or Rejected returns can be edited.")}
                )

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
                            "items": (
                                f"Line {index}: item does not belong to "
                                "the selected order."
                            )
                        }
                    )

                quantity = Decimal(str(item.get("returned_quantity", 0) or 0))

                returned_qs = SalesReturnItem.objects.filter(
                    sales_order_item=order_item
                ).exclude(sales_return__status__in=["REJECTED", "CANCELLED"])

                if self.instance:
                    returned_qs = returned_qs.exclude(sales_return=self.instance)

                already_returned = returned_qs.aggregate(
                    value=Sum("returned_quantity")
                )["value"] or Decimal("0")

                remaining = Decimal(str(order_item.quantity or 0)) - Decimal(
                    str(already_returned)
                )

                if quantity <= 0:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Line {index}: returned quantity must be "
                                "greater than zero."
                            )
                        }
                    )

                if quantity > remaining:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Line {index}: only {remaining} unit(s) "
                                "remain returnable."
                            )
                        }
                    )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        validated_data["return_number"] = self._generate_number()

        sales_return = SalesReturn.objects.create(**validated_data)

        for item in items:
            quantity = Decimal(str(item.get("returned_quantity", 0) or 0))
            price = Decimal(str(item.get("unit_price", 0) or 0))
            SalesReturnItem.objects.create(
                sales_return=sales_return,
                line_total=quantity * price,
                **item,
            )

        if sales_return.status == "PENDING_APPROVAL":
            sales_return.submitted_at = timezone.now()
            sales_return.save(update_fields=["submitted_at", "updated_at"])

        self._recalculate_totals(sales_return)
        return sales_return

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)

        for field, value in validated_data.items():
            if field in {
                "return_number",
                "submitted_at",
                "approved_at",
                "completed_at",
                "approved_by",
                "approver_name",
            }:
                continue
            setattr(instance, field, value)

        instance.save()

        if items is not None:
            instance.items.all().delete()

            for item in items:
                quantity = Decimal(str(item.get("returned_quantity", 0) or 0))
                price = Decimal(str(item.get("unit_price", 0) or 0))
                SalesReturnItem.objects.create(
                    sales_return=instance,
                    line_total=quantity * price,
                    **item,
                )

        self._recalculate_totals(instance)
        return instance


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
            "payment_number",
            "customer",
            "branch",
            "currency",
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

        payment_method = str(
            attrs.get("payment_method", getattr(self.instance, "payment_method", ""))
            or ""
        ).upper()
        bank_account = attrs.get(
            "bank_account", getattr(self.instance, "bank_account", None)
        )
        cash_register = attrs.get(
            "cash_register", getattr(self.instance, "cash_register", None)
        )

        if payment_method == "CASH":
            if not cash_register:
                raise serializers.ValidationError(
                    {"cash_register": "Cash Register is required for cash payments."}
                )
            attrs["bank_account"] = None
        elif payment_method in {"BANK_TRANSFER", "CARD", "CHEQUE"}:
            if not bank_account:
                raise serializers.ValidationError(
                    {
                        "bank_account": "Bank Account is required for this payment method."
                    }
                )
            attrs["cash_register"] = None
        elif payment_method == "OTHER" and not (bank_account or cash_register):
            raise serializers.ValidationError(
                {
                    "payment_method": "Select a Bank Account or Cash Register for Other payments."
                }
            )

        attrs["customer"] = invoice.customer
        attrs["branch"] = invoice.branch
        attrs["currency"] = invoice.currency

        if status_value == "PAID":
            attrs["cleared_at"] = timezone.now()

        return attrs

    def _update_invoice(self, invoice):
        total_paid = SalesPayment.objects.filter(
            invoice=invoice,
            status="PAID",
        ).aggregate(value=Sum("amount"))["value"] or Decimal("0")

        invoice.paid_amount = total_paid

        invoice.balance_due = max(
            Decimal("0"),
            Decimal(invoice.total_amount or 0) - total_paid,
        )

        if invoice.balance_due <= Decimal("0"):
            invoice.payment_status = "PAID"

            if hasattr(invoice, "paid_at"):
                invoice.paid_at = timezone.now()

        elif total_paid > Decimal("0"):
            invoice.payment_status = "PARTIALLY_PAID"

            if hasattr(invoice, "paid_at"):
                invoice.paid_at = None

        else:
            invoice.payment_status = "UNPAID"

            if hasattr(invoice, "paid_at"):
                invoice.paid_at = None

        update_fields = [
            "paid_amount",
            "balance_due",
            "payment_status",
            "updated_at",
        ]

        if hasattr(invoice, "paid_at"):
            update_fields.append("paid_at")

        invoice.save(update_fields=update_fields)

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
    product_sku = serializers.CharField(
        source="product.sku",
        read_only=True,
        allow_null=True,
    )
    base_price = serializers.SerializerMethodField()
    final_price = serializers.SerializerMethodField()

    class Meta:
        model = PriceListItem
        exclude = ["price_list"]

    def get_base_price(self, obj):
        return getattr(obj.product, "selling_price", 0) or 0

    def get_final_price(self, obj):
        base = Decimal(str(self.get_base_price(obj)))
        if obj.custom_price is not None:
            return obj.custom_price
        discount = Decimal(str(obj.discount_percentage or 0))
        return (base - (base * discount / Decimal("100"))).quantize(Decimal("0.01"))


class PriceListSerializer(serializers.ModelSerializer):
    items = PriceListItemSerializer(many=True, required=False)
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    item_count = serializers.IntegerField(source="items.count", read_only=True)
    applies_to_display = serializers.CharField(
        source="get_applies_to_display", read_only=True
    )
    type_display = serializers.CharField(
        source="get_price_list_type_display", read_only=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    discount_display = serializers.SerializerMethodField()

    class Meta:
        model = PriceList
        fields = "__all__"

    def get_discount_display(self, obj):
        item_discounts = list(obj.items.values_list("discount_percentage", flat=True))
        if obj.discount_type == "PERCENTAGE":
            return f"{obj.discount_percentage}%"
        if obj.discount_type == "FIXED":
            return f"{obj.currency or 'AED'} {obj.fixed_discount}"
        if item_discounts and any(Decimal(str(v or 0)) > 0 for v in item_discounts):
            return "Product rules"
        return "Fixed prices"

    def validate(self, attrs):
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get(
            "valid_until", getattr(self.instance, "valid_until", None)
        )
        status = attrs.get("status", getattr(self.instance, "status", "DRAFT"))
        price_list_type = attrs.get(
            "price_list_type",
            getattr(self.instance, "price_list_type", "CUSTOMER_TIER"),
        )
        branch = attrs.get("branch", getattr(self.instance, "branch", None))

        if valid_from and valid_until and valid_until < valid_from:
            raise serializers.ValidationError(
                {"valid_until": "Valid-until date cannot be before valid-from date."}
            )
        if price_list_type == "BRANCH_SPECIFIC" and not branch:
            raise serializers.ValidationError(
                {"branch": "Branch is required for a branch-specific price list."}
            )
        if status == "SCHEDULED" and not valid_from:
            raise serializers.ValidationError(
                {
                    "valid_from": "Valid-from date is required for a scheduled price list."
                }
            )
        return attrs

    def _save_relations(self, price_list, items, customer_ids):
        price_list.items.all().delete()
        for item in items:
            PriceListItem.objects.create(price_list=price_list, **item)

        price_list.customers.all().delete()
        for customer_id in customer_ids:
            PriceListCustomer.objects.get_or_create(
                price_list=price_list, customer_id=customer_id
            )

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        customer_ids = validated_data.pop("customer_ids", [])
        price_list = PriceList.objects.create(**validated_data)
        self._save_relations(price_list, items, customer_ids)
        return price_list

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        customer_ids = validated_data.pop("customer_ids", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items is not None or customer_ids is not None:
            self._save_relations(
                instance,
                (
                    items
                    if items is not None
                    else list(
                        instance.items.values(
                            "product",
                            "variant",
                            "custom_price",
                            "discount_percentage",
                            "minimum_quantity",
                        )
                    )
                ),
                (
                    customer_ids
                    if customer_ids is not None
                    else list(instance.customers.values_list("customer_id", flat=True))
                ),
            )
        return instance


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


class DeliveryNoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = DeliveryNoteItem
        exclude = ["delivery_note"]


class DeliveryNoteSerializer(serializers.ModelSerializer):
    items = DeliveryNoteItemSerializer(many=True)
    sales_order_number = serializers.CharField(
        source="sales_order.order_number", read_only=True
    )
    customer_name = serializers.CharField(
        source="customer.customer_name", read_only=True, allow_null=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, allow_null=True
    )

    class Meta:
        model = DeliveryNote
        fields = "__all__"
        read_only_fields = [
            "delivery_note_number",
            "dispatched_at",
            "delivered_at",
            "created_at",
            "updated_at",
        ]

    def _generate_number(self, branch):
        code = getattr(branch, "branch_code", None) or "DN"
        prefix = timezone.now().strftime(f"DN-{code}-%Y%m")
        count = DeliveryNote.objects.filter(
            delivery_note_number__startswith=prefix
        ).count()
        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        order = attrs.get("sales_order", getattr(self.instance, "sales_order", None))
        items = attrs.get("items")
        if not order:
            raise serializers.ValidationError(
                {"sales_order": "Sales order is required."}
            )
        if order.status == "CANCELLED":
            raise serializers.ValidationError(
                {"sales_order": "Cancelled sales orders cannot be delivered."}
            )
        if items is not None and not items:
            raise serializers.ValidationError(
                {"items": "Add at least one delivery item."}
            )
        for index, item in enumerate(items or [], start=1):
            qty = Decimal(str(item.get("delivered_quantity", 0) or 0))
            ordered = Decimal(str(item.get("ordered_quantity", 0) or 0))
            if qty <= 0:
                raise serializers.ValidationError(
                    {
                        "items": f"Line {index}: delivered quantity must be greater than zero."
                    }
                )
            if qty > ordered:
                raise serializers.ValidationError(
                    {
                        "items": f"Line {index}: delivered quantity cannot exceed ordered quantity."
                    }
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        order = validated_data["sales_order"]
        validated_data.setdefault("branch", order.branch)
        validated_data.setdefault("customer", order.customer)
        validated_data.setdefault("delivery_address", order.shipping_address)
        validated_data["delivery_note_number"] = self._generate_number(order.branch)
        note = DeliveryNote.objects.create(**validated_data)
        for item in items:
            DeliveryNoteItem.objects.create(delivery_note=note, **item)
        return note

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if items is not None:
            instance.items.all().delete()
            for item in items:
                DeliveryNoteItem.objects.create(delivery_note=instance, **item)
        return instance
