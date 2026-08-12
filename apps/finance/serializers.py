from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import (
    AccountingPeriod,
    BankAccount,
    Budget,
    BudgetLine,
    BudgetRevision,
    CashRegister,
    ChartOfAccount,
    Expense,
    ExpenseCategory,
    FixedAsset,
    FixedAssetAttachment,
    FixedAssetDepreciation,
    FixedAssetDisposal,
    FixedAssetTransfer,
    FixedAssetMaintenance,
    JournalEntry,
    JournalLine,
    JournalAttachment,
    LedgerEntry,
    ReceivableInvoice,
    ReceivableInvoiceLine,
    ReceivableReceipt,
    ReceivableInvoiceAttachment,
    TaxRate,
    VatSettings,
    VatReturn,
    VatReturnBox,
    BankTransaction,
    BankFundTransfer,
    AssetDepreciationRun,
    AssetDepreciationLine,
    AssetDisposal,
    PayableBill,
    PayableBillLine,
    PayablePayment,
    PayableBillAttachment,
)


class SimpleSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = "__all__"


class ExpenseSerializer(SimpleSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )

    class Meta:
        model = Expense
        fields = "__all__"


class CashRegisterSerializer(SimpleSerializer):
    class Meta:
        model = CashRegister
        fields = "__all__"


class BankAccountSerializer(SimpleSerializer):
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
    )

    account_type_display = serializers.CharField(
        source="get_account_type_display",
        read_only=True,
    )

    class Meta:
        model = BankAccount
        fields = "__all__"

    def validate(self, attrs):
        account_type = attrs.get(
            "account_type",
            getattr(
                self.instance,
                "account_type",
                "BANK",
            ),
        )

        bank_name = attrs.get(
            "bank_name",
            getattr(
                self.instance,
                "bank_name",
                "",
            ),
        )

        if account_type == "BANK" and not str(bank_name or "").strip():
            raise serializers.ValidationError(
                {"bank_name": ("Bank Name is required " "for bank accounts.")}
            )

        chart_account = attrs.get(
            "chart_account",
            getattr(
                self.instance,
                "chart_account",
                None,
            ),
        )

        if chart_account and chart_account.account_type != "ASSET":
            raise serializers.ValidationError(
                {
                    "chart_account": (
                        "Bank / Cash GL Account " "must be an Asset account."
                    )
                }
            )

        return attrs


class ChartOfAccountSerializer(SimpleSerializer):
    account_type_display = serializers.CharField(
        source="get_account_type_display",
        read_only=True,
    )
    sub_type_display = serializers.CharField(
        source="get_sub_type_display",
        read_only=True,
    )
    normal_balance_display = serializers.CharField(
        source="get_normal_balance_display",
        read_only=True,
    )
    tax_treatment_display = serializers.CharField(
        source="get_tax_treatment_display",
        read_only=True,
    )
    parent_name = serializers.CharField(
        source="parent.name",
        read_only=True,
        allow_null=True,
    )
    parent_code = serializers.CharField(
        source="parent.code",
        read_only=True,
        allow_null=True,
    )
    is_global = serializers.BooleanField(read_only=True)
    children_count = serializers.IntegerField(read_only=True, default=0)

    TYPE_PREFIXES = {
        "ASSET": "1",
        "LIABILITY": "2",
        "EQUITY": "3",
        "INCOME": "4",
        "EXPENSE": "5",
    }
    DEFAULT_NORMAL_BALANCE = {
        "ASSET": "DEBIT",
        "EXPENSE": "DEBIT",
        "LIABILITY": "CREDIT",
        "EQUITY": "CREDIT",
        "INCOME": "CREDIT",
    }

    class Meta:
        model = ChartOfAccount
        fields = "__all__"
        read_only_fields = ["current_balance"]

    def validate_code(self, value):
        code = str(value or "").strip()
        if not code.isdigit() or len(code) != 5:
            raise serializers.ValidationError(
                "Account code must contain exactly 5 digits."
            )
        return code

    def validate(self, attrs):
        account_type = attrs.get(
            "account_type",
            getattr(self.instance, "account_type", None),
        )
        code = attrs.get("code", getattr(self.instance, "code", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        branch = attrs.get("branch", getattr(self.instance, "branch", None))

        errors = {}
        prefix = self.TYPE_PREFIXES.get(account_type)
        if prefix and code and not code.startswith(prefix):
            errors["code"] = (
                f"{account_type.title()} account codes must start with {prefix}."
            )

        if parent:
            if self.instance and parent.pk == self.instance.pk:
                errors["parent"] = "An account cannot be its own parent."
            elif parent.account_type != account_type:
                errors["parent"] = "Parent account must have the same type."
            elif parent.branch_id not in (None, getattr(branch, "id", None)):
                errors["parent"] = "Parent account is not available for this branch."

        duplicate = ChartOfAccount.objects.filter(code=code, branch=branch)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if code and duplicate.exists():
            errors["code"] = "This account code already exists for the selected branch."

        if errors:
            raise serializers.ValidationError(errors)

        if not attrs.get("normal_balance") and account_type:
            attrs["normal_balance"] = self.DEFAULT_NORMAL_BALANCE[account_type]

        return attrs

    def create(self, validated_data):
        opening = Decimal(validated_data.get("opening_balance") or 0)
        validated_data["current_balance"] = opening
        return super().create(validated_data)

    def update(self, instance, validated_data):
        old_opening = Decimal(instance.opening_balance or 0)
        old_current = Decimal(instance.current_balance or 0)
        new_opening = Decimal(validated_data.get("opening_balance", old_opening) or 0)
        validated_data["current_balance"] = old_current - old_opening + new_opening
        return super().update(instance, validated_data)


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(
        source="account.code",
        read_only=True,
    )
    account_name = serializers.CharField(
        source="account.name",
        read_only=True,
    )

    class Meta:
        model = JournalLine
        fields = "__all__"
        read_only_fields = ["journal"]

    def validate(self, attrs):
        debit = Decimal(str(attrs.get("debit") or 0))
        credit = Decimal(str(attrs.get("credit") or 0))

        if debit < 0 or credit < 0:
            raise serializers.ValidationError("Debit and credit cannot be negative.")
        if debit > 0 and credit > 0:
            raise serializers.ValidationError("Enter either debit or credit, not both.")
        if debit == 0 and credit == 0:
            raise serializers.ValidationError("Debit or credit is required.")

        return attrs


class JournalAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = JournalAttachment
        fields = "__all__"
        read_only_fields = [
            "journal",
            "uploaded_by",
            "original_name",
            "created_at",
            "updated_at",
        ]

    def get_uploaded_by_name(self, obj):
        return str(obj.uploaded_by) if obj.uploaded_by else None

    def get_file_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return ""
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class JournalEntrySerializer(SimpleSerializer):
    lines = JournalLineSerializer(many=True)
    attachments = JournalAttachmentSerializer(many=True, read_only=True)

    total_debit = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    total_credit = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    difference = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    is_balanced = serializers.BooleanField(read_only=True)

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    voucher_type_display = serializers.CharField(
        source="get_voucher_type_display",
        read_only=True,
    )
    source_display = serializers.CharField(
        source="get_source_display",
        read_only=True,
    )
    approval_priority_display = serializers.CharField(
        source="get_approval_priority_display",
        read_only=True,
    )

    approver_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    rejected_by_name = serializers.SerializerMethodField()
    posted_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = "__all__"
        read_only_fields = [
            "entry_number",
            "status",
            "submitted_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "posted_by",
            "posted_at",
            "reversed_from",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def get_approver_name(self, obj):
        return str(obj.approver) if obj.approver else None

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None

    def get_rejected_by_name(self, obj):
        return str(obj.rejected_by) if obj.rejected_by else None

    def get_posted_by_name(self, obj):
        return str(obj.posted_by) if obj.posted_by else None

    def get_created_by_name(self, obj):
        return str(obj.created_by) if obj.created_by else None

    def get_updated_by_name(self, obj):
        return str(obj.updated_by) if obj.updated_by else None

    def _generate_number(self):
        prefix = timezone.now().strftime("JV-%Y%m")
        count = JournalEntry.objects.filter(entry_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        if self.instance and self.instance.status not in ["DRAFT", "REJECTED"]:
            raise serializers.ValidationError(
                {
                    "status": (
                        f"{self.instance.get_status_display()} journals "
                        "cannot be edited."
                    )
                }
            )

        lines = attrs.get("lines")
        if lines is None:
            lines = self.initial_data.get("lines", [])

        if len(lines) < 2:
            raise serializers.ValidationError(
                {"lines": "At least two journal lines are required."}
            )

        debit = sum(Decimal(str(item.get("debit") or 0)) for item in lines)
        credit = sum(Decimal(str(item.get("credit") or 0)) for item in lines)

        if debit <= 0:
            raise serializers.ValidationError(
                {"lines": "Journal total must be greater than zero."}
            )

        if debit != credit:
            raise serializers.ValidationError(
                {"lines": "Total debit must equal total credit."}
            )

        for index, item in enumerate(lines, start=1):
            line_debit = Decimal(str(item.get("debit") or 0))
            line_credit = Decimal(str(item.get("credit") or 0))

            if line_debit > 0 and line_credit > 0:
                raise serializers.ValidationError(
                    {
                        "lines": (
                            f"Line {index}: enter either debit or credit, " "not both."
                        )
                    }
                )

            if line_debit == 0 and line_credit == 0:
                raise serializers.ValidationError(
                    {"lines": (f"Line {index}: debit or credit is required.")}
                )

        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )

        account_ids = []
        for item in lines:
            account = item.get("account")
            if hasattr(account, "pk"):
                account_ids.append(account.pk)
            elif account:
                account_ids.append(account)

        accounts = ChartOfAccount.objects.filter(pk__in=account_ids)

        for account in accounts:
            if account.branch_id not in (
                None,
                getattr(branch, "id", None),
            ):
                raise serializers.ValidationError(
                    {
                        "lines": (
                            f"Account {account.code} is not available "
                            "for the selected branch."
                        )
                    }
                )

            if not account.is_active:
                raise serializers.ValidationError(
                    {"lines": (f"Account {account.code} is inactive.")}
                )

        posting_date = attrs.get(
            "entry_date",
            getattr(self.instance, "entry_date", None),
        )
        document_date = attrs.get(
            "document_date",
            getattr(self.instance, "document_date", None),
        )

        if not posting_date:
            raise serializers.ValidationError(
                {"entry_date": "Posting date is required."}
            )

        if not document_date:
            attrs["document_date"] = posting_date

        exchange_rate = Decimal(
            str(
                attrs.get(
                    "exchange_rate",
                    getattr(self.instance, "exchange_rate", 1),
                )
                or 0
            )
        )
        if exchange_rate <= 0:
            raise serializers.ValidationError(
                {"exchange_rate": "Exchange rate must be greater than zero."}
            )

        is_recurring = attrs.get(
            "is_recurring_template",
            getattr(self.instance, "is_recurring_template", False),
        )

        if is_recurring:
            frequency = attrs.get(
                "recurrence_frequency",
                getattr(self.instance, "recurrence_frequency", ""),
            )
            start_date = attrs.get(
                "recurrence_start_date",
                getattr(self.instance, "recurrence_start_date", None),
            )
            end_date = attrs.get(
                "recurrence_end_date",
                getattr(self.instance, "recurrence_end_date", None),
            )

            if not frequency:
                raise serializers.ValidationError(
                    {
                        "recurrence_frequency": (
                            "Frequency is required for recurring journals."
                        )
                    }
                )
            if not start_date:
                raise serializers.ValidationError(
                    {
                        "recurrence_start_date": (
                            "Start date is required for recurring journals."
                        )
                    }
                )
            if end_date and end_date < start_date:
                raise serializers.ValidationError(
                    {
                        "recurrence_end_date": (
                            "Recurring end date cannot be before start date."
                        )
                    }
                )

        is_reversing = attrs.get(
            "is_reversing",
            getattr(self.instance, "is_reversing", False),
        )
        if is_reversing:
            reversal_date = attrs.get(
                "reversal_date",
                getattr(self.instance, "reversal_date", None),
            )
            if not reversal_date:
                raise serializers.ValidationError(
                    {"reversal_date": "Reversal date is required."}
                )
            if posting_date and reversal_date <= posting_date:
                raise serializers.ValidationError(
                    {"reversal_date": ("Reversal date must be after posting date.")}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        validated_data["entry_number"] = self._generate_number()
        validated_data["status"] = "DRAFT"

        journal = JournalEntry.objects.create(**validated_data)

        for line in lines:
            JournalLine.objects.create(
                journal=journal,
                **line,
            )

        return journal

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status not in ["DRAFT", "REJECTED"]:
            raise serializers.ValidationError(
                {
                    "status": (
                        f"{instance.get_status_display()} journals " "cannot be edited."
                    )
                }
            )

        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)

        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                JournalLine.objects.create(
                    journal=instance,
                    **line,
                )

        return instance


class LedgerEntrySerializer(SimpleSerializer):
    account_name = serializers.CharField(
        source="account.name",
        read_only=True,
        allow_null=True,
    )
    account_code = serializers.CharField(
        source="account.code",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = LedgerEntry
        fields = "__all__"


class ReceivableInvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceivableInvoiceLine
        fields = "__all__"
        read_only_fields = [
            "invoice",
            "vat_rate",
            "amount",
            "discount_amount",
            "taxable_amount",
            "vat_amount",
            "line_total",
        ]


class ReceivableInvoiceAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ReceivableInvoiceAttachment
        fields = "__all__"
        read_only_fields = [
            "invoice",
            "original_name",
            "uploaded_by",
            "created_at",
            "updated_at",
        ]

    def get_file_url(self, obj):
        if not obj.file:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class ReceivableInvoiceSerializer(SimpleSerializer):
    lines = ReceivableInvoiceLineSerializer(many=True)
    attachments = ReceivableInvoiceAttachmentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    credit_terms_display = serializers.CharField(
        source="get_credit_terms_display", read_only=True
    )
    balance_due = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )
    currently_owed = serializers.SerializerMethodField()
    available_credit = serializers.SerializerMethodField()
    exceeds_credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = ReceivableInvoice
        fields = "__all__"
        read_only_fields = [
            "invoice_number",
            "status",
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "vat_amount",
            "total_amount",
            "paid_amount",
            "posted_at",
            "posted_by",
            "cancelled_at",
            "cancelled_by",
            "last_reminder_sent_at",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime("AR-%Y%m")
        count = ReceivableInvoice.objects.filter(
            invoice_number__startswith=prefix
        ).count()
        return f"{prefix}-{count + 1:04d}"

    def get_currently_owed(self, obj):
        values = (
            ReceivableInvoice.objects.filter(customer=obj.customer)
            .exclude(status__in=["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"])
            .exclude(pk=obj.pk)
            .aggregate(total=Sum("total_amount"), paid=Sum("paid_amount"))
        )
        return str(
            max(
                Decimal("0"),
                Decimal(values.get("total") or 0) - Decimal(values.get("paid") or 0),
            )
        )

    def get_available_credit(self, obj):
        limit = Decimal(obj.customer_credit_limit or 0)
        if limit <= 0:
            return "0"
        return str(max(Decimal("0"), limit - Decimal(self.get_currently_owed(obj))))

    def get_exceeds_credit_limit(self, obj):
        limit = Decimal(obj.customer_credit_limit or 0)
        return (
            False
            if limit <= 0
            else Decimal(self.get_currently_owed(obj)) + Decimal(obj.total_amount or 0)
            > limit
        )

    @staticmethod
    def _line_values(line):
        quantity = Decimal(str(line.get("quantity") or 0))
        unit_price = Decimal(str(line.get("unit_price") or 0))
        discount_percent = Decimal(str(line.get("discount_percent") or 0))
        tax_category = str(line.get("tax_category") or "STANDARD").upper()
        vat_rate = Decimal("5") if tax_category == "STANDARD" else Decimal("0")
        gross = (quantity * unit_price).quantize(Decimal("0.01"))
        discount = (gross * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
        taxable = max(Decimal("0"), gross - discount).quantize(Decimal("0.01"))
        vat = (taxable * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        return {
            "amount": gross,
            "discount_amount": discount,
            "taxable_amount": taxable,
            "vat_rate": vat_rate,
            "vat_amount": vat,
            "line_total": taxable + vat,
        }

    def validate(self, attrs):
        if self.instance and self.instance.status != "DRAFT":
            raise serializers.ValidationError(
                {
                    "status": f"{self.instance.get_status_display()} invoices cannot be edited."
                }
            )
        lines = attrs.get("lines") or self.initial_data.get("lines", [])
        if not lines:
            raise serializers.ValidationError(
                {"lines": "At least one invoice line is required."}
            )
        invoice_date = attrs.get(
            "invoice_date", getattr(self.instance, "invoice_date", None)
        )
        due_date = attrs.get("due_date", getattr(self.instance, "due_date", None))
        if invoice_date and due_date and due_date < invoice_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot be before invoice date."}
            )
        revenue = attrs.get(
            "revenue_account", getattr(self.instance, "revenue_account", None)
        )
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        if not revenue or revenue.account_type != "INCOME":
            raise serializers.ValidationError(
                {"revenue_account": "Select a valid Income / Revenue account."}
            )
        if revenue.branch_id not in (None, getattr(branch, "id", None)):
            raise serializers.ValidationError(
                {"revenue_account": "Revenue account is not available for this branch."}
            )
        for index, line in enumerate(lines, 1):
            if not str(line.get("item_service") or "").strip():
                raise serializers.ValidationError(
                    {"lines": f"Line {index}: Item / Service is required."}
                )
            if Decimal(str(line.get("quantity") or 0)) <= 0:
                raise serializers.ValidationError(
                    {"lines": f"Line {index}: Quantity must be greater than zero."}
                )
            discount = Decimal(str(line.get("discount_percent") or 0))
            if discount < 0 or discount > 100:
                raise serializers.ValidationError(
                    {"lines": f"Line {index}: Discount must be between 0 and 100."}
                )
        return attrs

    def _save_lines(self, invoice, lines):
        invoice.lines.all().delete()
        subtotal = discount_total = taxable_total = vat_total = grand_total = Decimal(
            "0"
        )
        for line in lines:
            v = self._line_values(line)
            subtotal += v["amount"]
            discount_total += v["discount_amount"]
            taxable_total += v["taxable_amount"]
            vat_total += v["vat_amount"]
            grand_total += v["line_total"]
            ReceivableInvoiceLine.objects.create(
                invoice=invoice,
                item_service=line.get("item_service", ""),
                description=line.get("description", ""),
                quantity=line.get("quantity", 1),
                unit_price=line.get("unit_price", 0),
                discount_percent=line.get("discount_percent", 0),
                tax_category=line.get("tax_category", "STANDARD"),
                **v,
            )
        invoice.subtotal = subtotal
        invoice.discount_amount = discount_total
        invoice.taxable_amount = taxable_total
        invoice.vat_amount = vat_total
        invoice.total_amount = grand_total

    def _validate_credit(self, invoice):
        limit = Decimal(invoice.customer_credit_limit or 0)
        if limit <= 0:
            return
        values = (
            ReceivableInvoice.objects.filter(customer=invoice.customer)
            .exclude(pk=invoice.pk)
            .exclude(status__in=["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"])
            .aggregate(total=Sum("total_amount"), paid=Sum("paid_amount"))
        )
        exposure = max(
            Decimal("0"),
            Decimal(values.get("total") or 0) - Decimal(values.get("paid") or 0),
        )
        if (
            exposure + Decimal(invoice.total_amount or 0) > limit
            and not invoice.credit_override_approved
        ):
            raise serializers.ValidationError(
                {
                    "credit_override_approved": "Customer credit limit is exceeded. Approved override is required."
                }
            )

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        invoice = ReceivableInvoice.objects.create(
            **validated_data,
            invoice_number=self._generate_number(),
            status="DRAFT",
            subtotal=0,
            discount_amount=0,
            taxable_amount=0,
            vat_amount=0,
            total_amount=0,
            paid_amount=0,
        )
        self._save_lines(invoice, lines)
        self._validate_credit(invoice)
        invoice.save(
            update_fields=[
                "subtotal",
                "discount_amount",
                "taxable_amount",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
        )
        return invoice

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status != "DRAFT":
            raise serializers.ValidationError(
                {
                    "status": f"{instance.get_status_display()} invoices cannot be edited."
                }
            )
        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)
        if lines is not None:
            self._save_lines(instance, lines)
            self._validate_credit(instance)
            instance.save(
                update_fields=[
                    "subtotal",
                    "discount_amount",
                    "taxable_amount",
                    "vat_amount",
                    "total_amount",
                    "updated_at",
                ]
            )
        return instance


class ReceivableReceiptSerializer(SimpleSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, allow_null=True
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    allocated_amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )
    unallocated_amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )

    class Meta:
        model = ReceivableReceipt
        fields = "__all__"
        read_only_fields = ["receipt_number"]

    def validate(self, attrs):
        invoice = attrs.get("invoice")
        customer = attrs.get("customer")
        branch = attrs.get("branch")
        amount = Decimal(str(attrs.get("amount") or 0))
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Receipt amount must be greater than zero."}
            )
        if invoice:
            if invoice.customer_id != customer.id or invoice.branch_id != branch.id:
                raise serializers.ValidationError(
                    {
                        "invoice": "Invoice must belong to the selected customer and branch."
                    }
                )
            if invoice.status in ["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"]:
                raise serializers.ValidationError(
                    {"invoice": "Receipt cannot be allocated to this invoice."}
                )
            if amount > Decimal(invoice.balance_due or 0):
                raise serializers.ValidationError(
                    {"amount": "Receipt amount cannot exceed invoice balance."}
                )
        return attrs

    def create(self, validated_data):
        prefix = timezone.now().strftime("RCPT-%Y%m")
        count = ReceivableReceipt.objects.filter(
            receipt_number__startswith=prefix
        ).count()
        validated_data["receipt_number"] = f"{prefix}-{count + 1:04d}"
        return super().create(validated_data)


class FixedAssetAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = FixedAssetAttachment
        fields = "__all__"
        read_only_fields = ["asset", "original_name", "uploaded_by"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        return (
            request.build_absolute_uri(obj.file.url)
            if request and obj.file
            else (obj.file.url if obj.file else "")
        )


class FixedAssetSerializer(SimpleSerializer):
    attachments = FixedAssetAttachmentSerializer(many=True, read_only=True)
    net_book_value = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )
    capitalized_cost = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )

    class Meta:
        model = FixedAsset
        fields = "__all__"
        read_only_fields = [
            "asset_tag",
            "status",
            "accumulated_depreciation",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "capitalized_by",
            "capitalized_at",
        ]

    def validate(self, attrs):
        if self.instance and self.instance.status not in ["DRAFT", "REJECTED"]:
            raise serializers.ValidationError(
                {"status": "Only Draft or Rejected assets can be edited."}
            )
        cost = Decimal(
            str(
                attrs.get(
                    "acquisition_cost", getattr(self.instance, "acquisition_cost", 0)
                )
                or 0
            )
        )
        residual = Decimal(
            str(
                attrs.get("residual_value", getattr(self.instance, "residual_value", 0))
                or 0
            )
        )
        if cost <= 0:
            raise serializers.ValidationError(
                {"acquisition_cost": "Acquisition cost must be greater than zero."}
            )
        if residual < 0 or residual > cost:
            raise serializers.ValidationError(
                {
                    "residual_value": "Residual value must be between zero and acquisition cost."
                }
            )
        return attrs

    def create(self, validated_data):
        prefix = timezone.now().strftime("FA-%Y%m")
        count = FixedAsset.objects.filter(asset_tag__startswith=prefix).count()
        validated_data["asset_tag"] = f"{prefix}-{count + 1:04d}"
        return super().create(validated_data)


class FixedAssetDepreciationSerializer(SimpleSerializer):
    asset_name = serializers.CharField(source="asset.asset_name", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)

    class Meta:
        model = FixedAssetDepreciation
        fields = "__all__"


class FixedAssetTransferSerializer(SimpleSerializer):
    asset_name = serializers.CharField(source="asset.asset_name", read_only=True)

    class Meta:
        model = FixedAssetTransfer
        fields = "__all__"
        read_only_fields = [
            "transfer_number",
            "from_location",
            "from_custodian",
            "status",
            "approved_by",
        ]

    def create(self, validated_data):
        asset = validated_data["asset"]
        prefix = timezone.now().strftime("AT-%Y%m")
        validated_data.update(
            {
                "transfer_number": f"{prefix}-{FixedAssetTransfer.objects.filter(transfer_number__startswith=prefix).count()+1:04d}",
                "branch": asset.branch,
                "from_location": asset.location,
                "from_custodian": asset.custodian,
            }
        )
        return super().create(validated_data)


class FixedAssetMaintenanceSerializer(SimpleSerializer):
    asset_name = serializers.CharField(source="asset.asset_name", read_only=True)

    class Meta:
        model = FixedAssetMaintenance
        fields = "__all__"
        read_only_fields = ["job_number"]

    def create(self, validated_data):
        prefix = timezone.now().strftime("MT-%Y%m")
        validated_data["job_number"] = (
            f"{prefix}-{FixedAssetMaintenance.objects.filter(job_number__startswith=prefix).count()+1:04d}"
        )
        return super().create(validated_data)


class FixedAssetDisposalSerializer(SimpleSerializer):
    asset_name = serializers.CharField(source="asset.asset_name", read_only=True)

    class Meta:
        model = FixedAssetDisposal
        fields = "__all__"
        read_only_fields = [
            "disposal_number",
            "original_cost",
            "accumulated_depreciation",
            "net_book_value",
            "gain_loss",
            "status",
            "journal_reference",
        ]

    def create(self, validated_data):
        asset = validated_data["asset"]
        prefix = timezone.now().strftime("DSP-%Y%m")
        validated_data.update(
            {
                "disposal_number": f"{prefix}-{FixedAssetDisposal.objects.filter(disposal_number__startswith=prefix).count()+1:04d}",
                "branch": asset.branch,
                "original_cost": asset.capitalized_cost,
                "accumulated_depreciation": asset.accumulated_depreciation,
                "net_book_value": asset.net_book_value,
                "gain_loss": Decimal(str(validated_data.get("proceeds", 0)))
                - asset.net_book_value,
            }
        )
        return super().create(validated_data)


class TaxRateSerializer(SimpleSerializer):
    class Meta:
        model = TaxRate
        fields = "__all__"


class BudgetLineSerializer(serializers.ModelSerializer):
    annual_total = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    account_code = serializers.CharField(
        source="account.code",
        read_only=True,
    )
    account_name = serializers.CharField(
        source="account.name",
        read_only=True,
    )
    branch_name = serializers.SerializerMethodField()

    class Meta:
        model = BudgetLine
        fields = "__all__"
        read_only_fields = [
            "budget",
        ]

    def get_branch_name(self, obj):
        if not obj.branch:
            return "All Branches"
        return getattr(obj.branch, "branch_name", None) or getattr(
            obj.branch, "name", ""
        )


class BudgetSerializer(serializers.ModelSerializer):
    lines = BudgetLineSerializer(
        many=True,
    )
    total_budget = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )

    budget_owner_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    rejected_by_name = serializers.SerializerMethodField()
    activated_by_name = serializers.SerializerMethodField()
    version_label = serializers.SerializerMethodField()
    branch_scope_name = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = "__all__"
        read_only_fields = [
            "budget_number",
            "version",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "activated_by",
            "activated_at",
        ]

    def get_budget_owner_name(self, obj):
        return str(obj.budget_owner) if obj.budget_owner else None

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None

    def get_rejected_by_name(self, obj):
        return str(obj.rejected_by) if obj.rejected_by else None

    def get_activated_by_name(self, obj):
        return str(obj.activated_by) if obj.activated_by else None

    def get_version_label(self, obj):
        return f"Rev {obj.version}"

    def get_branch_scope_name(self, obj):
        if not obj.branch_scope:
            return "All Branches"
        return getattr(
            obj.branch_scope,
            "branch_name",
            None,
        ) or getattr(
            obj.branch_scope,
            "name",
            "",
        )

    def _generate_number(self):
        prefix = timezone.now().strftime("BUD-%Y")
        count = Budget.objects.filter(budget_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def validate(self, attrs):
        if self.instance and self.instance.status not in [
            "DRAFT",
            "REJECTED",
        ]:
            raise serializers.ValidationError(
                {
                    "status": (
                        f"{self.instance.get_status_display()} "
                        "budgets cannot be edited directly."
                    )
                }
            )

        start_date = attrs.get(
            "start_date",
            getattr(
                self.instance,
                "start_date",
                None,
            ),
        )
        end_date = attrs.get(
            "end_date",
            getattr(
                self.instance,
                "end_date",
                None,
            ),
        )

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": ("End date cannot be before start date.")}
            )

        warning = Decimal(
            str(
                attrs.get(
                    "warning_threshold_percent",
                    getattr(
                        self.instance,
                        "warning_threshold_percent",
                        80,
                    ),
                )
                or 0
            )
        )

        block = Decimal(
            str(
                attrs.get(
                    "block_threshold_percent",
                    getattr(
                        self.instance,
                        "block_threshold_percent",
                        100,
                    ),
                )
                or 0
            )
        )

        if warning > block:
            raise serializers.ValidationError(
                {
                    "warning_threshold_percent": (
                        "Warning threshold cannot exceed " "block threshold."
                    )
                }
            )

        lines = attrs.get("lines")

        if lines is None:
            lines = self.initial_data.get(
                "lines",
                [],
            )

        if not lines:
            raise serializers.ValidationError(
                {"lines": ("At least one budget line is required.")}
            )

        return attrs

    def _save_lines(
        self,
        budget,
        lines,
    ):
        budget.lines.all().delete()

        for line in lines:
            BudgetLine.objects.create(
                budget=budget,
                **line,
            )

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        lines = validated_data.pop(
            "lines",
            [],
        )

        budget = Budget.objects.create(
            **validated_data,
            budget_number=self._generate_number(),
            status="DRAFT",
            version=1,
        )

        self._save_lines(
            budget,
            lines,
        )

        return budget

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        lines = validated_data.pop(
            "lines",
            None,
        )

        instance = super().update(
            instance,
            validated_data,
        )

        if lines is not None:
            self._save_lines(
                instance,
                lines,
            )

        return instance


class BudgetRevisionSerializer(serializers.ModelSerializer):
    budget_name = serializers.CharField(
        source="budget.budget_name",
        read_only=True,
    )
    from_account_name = serializers.CharField(
        source="from_account.name",
        read_only=True,
        allow_null=True,
    )
    to_account_name = serializers.CharField(
        source="to_account.name",
        read_only=True,
        allow_null=True,
    )
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BudgetRevision
        fields = "__all__"
        read_only_fields = [
            "revision_number",
            "status",
            "approved_by",
            "approved_at",
        ]

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None

    def create(
        self,
        validated_data,
    ):
        prefix = timezone.now().strftime("BREV-%Y%m")
        count = BudgetRevision.objects.filter(
            revision_number__startswith=prefix
        ).count()

        validated_data["revision_number"] = f"{prefix}-{count + 1:04d}"

        return super().create(validated_data)


class VatReturnBoxSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatReturnBox
        fields = "__all__"
        read_only_fields = [
            "vat_return",
        ]


class VatReturnSerializer(serializers.ModelSerializer):
    boxes = VatReturnBoxSerializer(
        many=True,
        read_only=True,
    )
    branch_scope_name = serializers.SerializerMethodField()
    assigned_approver_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    filed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VatReturn
        fields = "__all__"
        read_only_fields = [
            "output_vat",
            "input_vat",
            "net_vat_payable",
            "total_transactions",
            "valid_transactions",
            "warnings_count",
            "errors_count",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "submission_date",
            "filed_by",
            "status",
        ]

    def get_branch_scope_name(self, obj):
        if not obj.branch_scope:
            return "All Branches"
        return getattr(
            obj.branch_scope,
            "branch_name",
            None,
        ) or getattr(
            obj.branch_scope,
            "name",
            "",
        )

    def get_assigned_approver_name(self, obj):
        return str(obj.assigned_approver) if obj.assigned_approver else None

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None

    def get_filed_by_name(self, obj):
        return str(obj.filed_by) if obj.filed_by else None

    def validate(self, attrs):
        period_from = attrs.get(
            "period_from",
            getattr(
                self.instance,
                "period_from",
                None,
            ),
        )
        period_to = attrs.get(
            "period_to",
            getattr(
                self.instance,
                "period_to",
                None,
            ),
        )

        if period_from and period_to and period_to < period_from:
            raise serializers.ValidationError(
                {"period_to": ("Period To cannot be before Period From.")}
            )

        return attrs


class VatSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatSettings
        fields = "__all__"

    def validate(self, attrs):
        for field in [
            "output_vat_account",
            "input_vat_account",
            "vat_payable_account",
        ]:
            account = attrs.get(
                field,
                getattr(
                    self.instance,
                    field,
                    None,
                ),
            )

            if account and not account.is_active:
                raise serializers.ValidationError(
                    {field: ("Selected account is inactive.")}
                )

        return attrs


class AccountingPeriodSerializer(SimpleSerializer):
    class Meta:
        model = AccountingPeriod
        fields = "__all__"
        read_only_fields = ["closed_by", "closed_at"]


class BankTransactionSerializer(SimpleSerializer):
    bank_account_name = serializers.CharField(
        source="bank_account.account_name",
        read_only=True,
    )

    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display",
        read_only=True,
    )

    class Meta:
        model = BankTransaction
        fields = "__all__"
        read_only_fields = [
            "voucher_number",
            "running_balance",
            "reconciliation_status",
            "reconciled_at",
            "reconciled_by",
        ]

    def validate(self, attrs):
        account = attrs.get("bank_account")

        branch = attrs.get("branch")

        receipt = Decimal(
            str(
                attrs.get(
                    "receipt_amount",
                    0,
                )
                or 0
            )
        )

        payment = Decimal(
            str(
                attrs.get(
                    "payment_amount",
                    0,
                )
                or 0
            )
        )

        if account.branch_id != branch.id:
            raise serializers.ValidationError(
                {"bank_account": ("Account does not belong " "to the selected branch.")}
            )

        if receipt > 0 and payment > 0:
            raise serializers.ValidationError(
                "Enter either Receipt or Payment amount, not both."
            )

        if receipt <= 0 and payment <= 0:
            raise serializers.ValidationError("Receipt or Payment amount is required.")

        if payment > Decimal(account.current_balance or 0):
            raise serializers.ValidationError(
                {"payment_amount": ("Insufficient balance " "in the selected account.")}
            )

        return attrs

    def create(self, validated_data):
        prefix = timezone.now().strftime("CV-%Y%m")

        count = BankTransaction.objects.filter(
            voucher_number__startswith=prefix
        ).count()

        validated_data["voucher_number"] = f"{prefix}-{count + 1:04d}"

        return super().create(validated_data)


class BankFundTransferSerializer(SimpleSerializer):
    from_account_name = serializers.CharField(
        source="from_account.account_name",
        read_only=True,
    )

    to_account_name = serializers.CharField(
        source="to_account.account_name",
        read_only=True,
    )

    class Meta:
        model = BankFundTransfer
        fields = "__all__"
        read_only_fields = [
            "reference_number",
            "status",
            "journal",
        ]

    def validate(self, attrs):
        source = attrs.get("from_account")

        destination = attrs.get("to_account")

        branch = attrs.get("branch")

        amount = Decimal(
            str(
                attrs.get(
                    "amount",
                    0,
                )
                or 0
            )
        )

        if source == destination:
            raise serializers.ValidationError(
                {"to_account": ("Source and destination " "accounts must differ.")}
            )

        if source.branch_id != branch.id or destination.branch_id != branch.id:
            raise serializers.ValidationError(
                {"branch": ("Both accounts must belong " "to the selected branch.")}
            )

        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": ("Transfer amount must " "be greater than zero.")}
            )

        if amount > Decimal(source.current_balance or 0):
            raise serializers.ValidationError(
                {"amount": ("Insufficient source-account balance.")}
            )

        return attrs

    def create(self, validated_data):
        prefix = timezone.now().strftime("FT-%Y%m")

        count = BankFundTransfer.objects.filter(
            reference_number__startswith=prefix
        ).count()

        validated_data["reference_number"] = f"{prefix}-{count + 1:04d}"

        return super().create(validated_data)


class AssetDepreciationLineSerializer(serializers.ModelSerializer):
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    asset_code = serializers.CharField(source="asset.asset_code", read_only=True)

    class Meta:
        model = AssetDepreciationLine
        fields = "__all__"
        read_only_fields = ["run"]


class AssetDepreciationRunSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    lines = AssetDepreciationLineSerializer(many=True, read_only=True)

    class Meta:
        model = AssetDepreciationRun
        fields = "__all__"


class AssetDisposalSerializer(SimpleSerializer):
    asset_name = serializers.CharField(
        source="asset.name",
        read_only=True,
    )
    asset_code = serializers.CharField(
        source="asset.asset_code",
        read_only=True,
    )
    disposal_method_display = serializers.CharField(
        source="get_disposal_method_display",
        read_only=True,
    )

    class Meta:
        model = AssetDisposal
        fields = "__all__"
        read_only_fields = [
            "net_book_value",
            "gain_or_loss",
            "journal",
        ]

    def validate(self, attrs):
        asset = attrs.get(
            "asset",
            getattr(self.instance, "asset", None),
        )
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )
        method = attrs.get(
            "disposal_method",
            getattr(self.instance, "disposal_method", None),
        )
        proceeds = Decimal(
            attrs.get(
                "sale_proceeds",
                getattr(self.instance, "sale_proceeds", 0),
            )
            or 0
        )
        disposal_date = attrs.get(
            "disposal_date",
            getattr(self.instance, "disposal_date", None),
        )

        errors = {}

        if asset and asset.status != "ACTIVE":
            errors["asset"] = "Only active assets can be disposed."

        if asset and branch and asset.branch_id != branch.id:
            errors["branch"] = "The disposal branch must match the asset branch."

        if asset and disposal_date and disposal_date < asset.purchase_date:
            errors["disposal_date"] = (
                "Disposal date cannot be before the purchase date."
            )

        if method == "SOLD" and proceeds < 0:
            errors["sale_proceeds"] = "Sale proceeds cannot be negative."

        if method != "SOLD":
            attrs["sale_proceeds"] = Decimal("0")

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        asset = validated_data["asset"]
        net_book_value = Decimal(asset.book_value or 0)
        sale_proceeds = Decimal(validated_data.get("sale_proceeds") or 0)

        validated_data["net_book_value"] = net_book_value
        validated_data["gain_or_loss"] = sale_proceeds - net_book_value

        disposal = super().create(validated_data)

        asset.status = "DISPOSED"

        update_fields = [
            "status",
            "updated_at",
        ]

        if validated_data.get("retire_tag") and hasattr(
            asset,
            "tag_retired",
        ):
            asset.tag_retired = True
            update_fields.append("tag_retired")

        asset.save(update_fields=update_fields)

        return disposal


class PayableBillLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayableBillLine
        fields = "__all__"
        read_only_fields = [
            "bill",
            "vat_rate",
            "amount",
            "discount_amount",
            "taxable_amount",
            "vat_amount",
            "line_total",
        ]


class PayableBillAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = PayableBillAttachment
        fields = "__all__"
        read_only_fields = [
            "bill",
            "original_name",
            "uploaded_by",
            "created_at",
            "updated_at",
        ]

    def get_file_url(self, obj):
        if not obj.file:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class PayableBillSerializer(SimpleSerializer):
    lines = PayableBillLineSerializer(many=True)
    attachments = PayableBillAttachmentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    balance_due = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )

    class Meta:
        model = PayableBill
        fields = "__all__"
        read_only_fields = [
            "bill_number",
            "status",
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "vat_amount",
            "withholding_tax_amount",
            "total_amount",
            "paid_amount",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "matched_by",
            "matched_at",
            "posted_by",
            "posted_at",
        ]

    def _generate_number(self):
        prefix = timezone.now().strftime("BILL-%Y%m")
        count = PayableBill.objects.filter(bill_number__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"

    def _line_values(self, line):
        qty = Decimal(str(line.get("quantity") or 0))
        price = Decimal(str(line.get("unit_price") or 0))
        disc_pct = Decimal(str(line.get("discount_percent") or 0))
        tax_category = str(line.get("tax_category") or "STANDARD").upper()
        rate = Decimal("5") if tax_category == "STANDARD" else Decimal("0")

        gross = (qty * price).quantize(Decimal("0.01"))
        discount = (gross * disc_pct / Decimal("100")).quantize(Decimal("0.01"))
        taxable = max(Decimal("0"), gross - discount).quantize(Decimal("0.01"))
        vat = (taxable * rate / Decimal("100")).quantize(Decimal("0.01"))

        return {
            "amount": gross,
            "discount_amount": discount,
            "taxable_amount": taxable,
            "vat_rate": rate,
            "vat_amount": vat,
            "line_total": taxable + vat,
        }

    def validate(self, attrs):
        if self.instance and self.instance.status not in ["DRAFT", "REJECTED"]:
            raise serializers.ValidationError(
                {
                    "status": f"{self.instance.get_status_display()} bills cannot be edited."
                }
            )

        lines = attrs.get("lines")
        if lines is None:
            lines = self.initial_data.get("lines", [])

        if not lines:
            raise serializers.ValidationError(
                {"lines": "At least one bill line is required."}
            )

        bill_date = attrs.get("bill_date", getattr(self.instance, "bill_date", None))
        due_date = attrs.get("due_date", getattr(self.instance, "due_date", None))
        if bill_date and due_date and due_date < bill_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot be before bill date."}
            )

        account = attrs.get(
            "expense_account", getattr(self.instance, "expense_account", None)
        )
        if not account:
            raise serializers.ValidationError(
                {"expense_account": "Expense / Inventory Account is required."}
            )

        for index, line in enumerate(lines, 1):
            if not str(line.get("item_expense") or "").strip():
                raise serializers.ValidationError(
                    {"lines": f"Line {index}: Item / Expense is required."}
                )
            if Decimal(str(line.get("quantity") or 0)) <= 0:
                raise serializers.ValidationError(
                    {"lines": f"Line {index}: Quantity must be greater than zero."}
                )

        return attrs

    def _save_lines(self, bill, lines):
        bill.lines.all().delete()
        subtotal = discount = taxable = vat = Decimal("0")

        for line in lines:
            values = self._line_values(line)
            subtotal += values["amount"]
            discount += values["discount_amount"]
            taxable += values["taxable_amount"]
            vat += values["vat_amount"]

            PayableBillLine.objects.create(
                bill=bill,
                item_expense=line.get("item_expense", ""),
                description=line.get("description", ""),
                quantity=line.get("quantity", 1),
                unit_price=line.get("unit_price", 0),
                discount_percent=line.get("discount_percent", 0),
                tax_category=line.get("tax_category", "STANDARD"),
                **values,
            )

        tds = (
            taxable * Decimal(str(bill.withholding_tax_rate or 0)) / Decimal("100")
            if bill.apply_withholding_tax
            else Decimal("0")
        )

        bill.subtotal = subtotal
        bill.discount_amount = discount
        bill.taxable_amount = taxable
        bill.vat_amount = vat
        bill.withholding_tax_amount = tds
        bill.total_amount = taxable + vat - tds

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        bill = PayableBill.objects.create(
            **validated_data,
            bill_number=self._generate_number(),
            status="DRAFT",
        )
        self._save_lines(bill, lines)
        bill.save()
        return bill

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status not in ["DRAFT", "REJECTED"]:
            raise serializers.ValidationError(
                {"status": f"{instance.get_status_display()} bills cannot be edited."}
            )

        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)

        if lines is not None:
            self._save_lines(instance, lines)
            instance.save()

        return instance


class PayablePaymentSerializer(SimpleSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = PayablePayment
        fields = "__all__"
        read_only_fields = ["payment_number"]

    def validate(self, attrs):
        bill = attrs.get("bill")
        supplier = attrs.get("supplier")
        branch = attrs.get("branch")
        amount = Decimal(str(attrs.get("amount") or 0))

        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Payment amount must be greater than zero."}
            )
        if bill.supplier_id != supplier.id:
            raise serializers.ValidationError({"bill": "Bill supplier does not match."})
        if bill.branch_id != branch.id:
            raise serializers.ValidationError({"bill": "Bill branch does not match."})
        if bill.status not in ["POSTED", "PARTIALLY_PAID", "OVERDUE"]:
            raise serializers.ValidationError(
                {"bill": "This bill is not available for payment."}
            )
        if amount > bill.balance_due:
            raise serializers.ValidationError(
                {"amount": "Payment cannot exceed the bill balance."}
            )

        return attrs

    def create(self, validated_data):
        prefix = timezone.now().strftime("PAY-%Y%m")
        count = PayablePayment.objects.filter(payment_number__startswith=prefix).count()
        validated_data["payment_number"] = f"{prefix}-{count + 1:04d}"
        return super().create(validated_data)
