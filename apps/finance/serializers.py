from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import (
    AccountingPeriod,
    BankAccount,
    Budget,
    CashRegister,
    ChartOfAccount,
    Expense,
    ExpenseCategory,
    FixedAsset,
    JournalEntry,
    JournalLine,
    LedgerEntry,
    ReceivableInvoice,
    ReceivableInvoiceLine,
    ReceivableReceipt,
    TaxRate,
    BankTransaction,
    BankFundTransfer,
    AssetDepreciationRun,
    AssetDepreciationLine,
    AssetDisposal,
    PayableBill,
    PayableBillLine,
    PayablePayment,
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
    class Meta:
        model = BankAccount
        fields = "__all__"


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
    account_name = serializers.CharField(
        source="account.name",
        read_only=True,
    )
    account_code = serializers.CharField(
        source="account.code",
        read_only=True,
    )

    class Meta:
        model = JournalLine
        fields = "__all__"
        read_only_fields = ["journal"]

    def validate(self, attrs):
        debit = Decimal(attrs.get("debit") or 0)
        credit = Decimal(attrs.get("credit") or 0)

        if debit < 0 or credit < 0:
            raise serializers.ValidationError("Debit and credit cannot be negative.")
        if debit and credit:
            raise serializers.ValidationError(
                "A line cannot contain both debit and credit."
            )
        if not debit and not credit:
            raise serializers.ValidationError("Enter either a debit or credit amount.")

        account = attrs.get("account")
        if account and (not account.is_active or account.lock_from_posting):
            raise serializers.ValidationError(
                "The selected account is inactive or locked from posting."
            )

        return attrs


class JournalEntrySerializer(SimpleSerializer):
    lines = JournalLineSerializer(many=True)
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
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    voucher_type_display = serializers.CharField(
        source="get_voucher_type_display",
        read_only=True,
    )
    approver_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    posted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = "__all__"
        read_only_fields = [
            "approved_by",
            "approved_at",
            "posted_by",
            "posted_at",
        ]

    def get_approver_name(self, obj):
        return str(obj.approver) if obj.approver else None

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None

    def get_posted_by_name(self, obj):
        return str(obj.posted_by) if obj.posted_by else None

    def validate(self, attrs):
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

        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None),
        )
        account_ids = [item.get("account") for item in lines if item.get("account")]
        accounts = ChartOfAccount.objects.filter(pk__in=account_ids)

        for account in accounts:
            if account.branch_id not in (None, getattr(branch, "id", None)):
                raise serializers.ValidationError(
                    {
                        "lines": (
                            f"Account {account.code} is not available "
                            "for the selected branch."
                        )
                    }
                )

        if attrs.get("is_reversing") and not attrs.get("reversal_date"):
            raise serializers.ValidationError(
                {"reversal_date": "Reversal date is required."}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        journal = JournalEntry.objects.create(**validated_data)

        for line in lines:
            serializer = JournalLineSerializer(data=line)
            serializer.is_valid(raise_exception=True)
            JournalLine.objects.create(journal=journal, **serializer.validated_data)

        return journal

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.status == "POSTED":
            raise serializers.ValidationError("Posted journals cannot be edited.")

        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)

        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                serializer = JournalLineSerializer(data=line)
                serializer.is_valid(raise_exception=True)
                JournalLine.objects.create(
                    journal=instance,
                    **serializer.validated_data,
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
        read_only_fields = ["invoice", "amount", "vat_amount"]


class ReceivableReceiptSerializer(SimpleSerializer):
    customer_name = serializers.CharField(
        source="customer.name",
        read_only=True,
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
    )

    class Meta:
        model = ReceivableReceipt
        fields = "__all__"


class ReceivableInvoiceSerializer(SimpleSerializer):
    lines = ReceivableInvoiceLineSerializer(many=True)
    customer_name = serializers.CharField(
        source="customer.name",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    credit_terms_display = serializers.CharField(
        source="get_credit_terms_display",
        read_only=True,
    )
    balance_due = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    currently_owed = serializers.SerializerMethodField()
    available_credit = serializers.SerializerMethodField()
    exceeds_credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = ReceivableInvoice
        fields = "__all__"
        read_only_fields = [
            "subtotal",
            "vat_amount",
            "total_amount",
            "paid_amount",
        ]

    def get_currently_owed(self, obj):
        value = (
            ReceivableInvoice.objects.filter(customer=obj.customer)
            .exclude(status__in=["PAID", "CANCELLED", "WRITTEN_OFF"])
            .exclude(pk=obj.pk)
            .aggregate(value=Sum("total_amount") - Sum("paid_amount"))
            .get("value")
        )
        return str(value or Decimal("0"))

    def get_available_credit(self, obj):
        owed = Decimal(self.get_currently_owed(obj))
        return str(max(Decimal("0"), obj.customer_credit_limit - owed))

    def get_exceeds_credit_limit(self, obj):
        owed = Decimal(self.get_currently_owed(obj))
        return owed + obj.total_amount > obj.customer_credit_limit

    def validate(self, attrs):
        lines = self.initial_data.get("lines", [])
        if not lines:
            raise serializers.ValidationError(
                {"lines": "At least one invoice line is required."}
            )

        invoice_date = attrs.get(
            "invoice_date",
            getattr(self.instance, "invoice_date", None),
        )
        due_date = attrs.get(
            "due_date",
            getattr(self.instance, "due_date", None),
        )
        if invoice_date and due_date and due_date < invoice_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot be before invoice date."}
            )

        return attrs

    @staticmethod
    def _line_values(line):
        quantity = Decimal(str(line.get("quantity") or 0))
        unit_price = Decimal(str(line.get("unit_price") or 0))
        vat_rate = Decimal(str(line.get("vat_rate") or 0))
        amount = (quantity * unit_price).quantize(Decimal("0.01"))
        vat_amount = (amount * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        return amount, vat_amount

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        subtotal = Decimal("0")
        vat_amount = Decimal("0")

        invoice = ReceivableInvoice.objects.create(
            **validated_data,
            subtotal=0,
            vat_amount=0,
            total_amount=0,
        )

        for line in lines:
            amount, line_vat = self._line_values(line)
            subtotal += amount
            vat_amount += line_vat
            ReceivableInvoiceLine.objects.create(
                invoice=invoice,
                description=line.get("description", ""),
                quantity=line.get("quantity", 1),
                unit_price=line.get("unit_price", 0),
                vat_rate=line.get("vat_rate", 0),
                amount=amount,
                vat_amount=line_vat,
            )

        invoice.subtotal = subtotal
        invoice.vat_amount = vat_amount
        invoice.total_amount = subtotal + vat_amount

        currently_owed = ReceivableInvoice.objects.filter(
            customer=invoice.customer
        ).exclude(pk=invoice.pk).exclude(
            status__in=["PAID", "CANCELLED", "WRITTEN_OFF"]
        ).aggregate(
            value=Sum("total_amount") - Sum("paid_amount")
        ).get(
            "value"
        ) or Decimal(
            "0"
        )

        if (
            invoice.customer_credit_limit > 0
            and currently_owed + invoice.total_amount > invoice.customer_credit_limit
            and not invoice.credit_override_approved
        ):
            raise serializers.ValidationError(
                {
                    "credit_override_approved": (
                        "This invoice exceeds the customer's credit limit. "
                        "Approval is required."
                    )
                }
            )

        invoice.save(
            update_fields=[
                "subtotal",
                "vat_amount",
                "total_amount",
                "updated_at",
            ]
        )
        return invoice

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)

        if lines is not None:
            instance.lines.all().delete()
            subtotal = Decimal("0")
            vat_amount = Decimal("0")

            for line in lines:
                amount, line_vat = self._line_values(line)
                subtotal += amount
                vat_amount += line_vat
                ReceivableInvoiceLine.objects.create(
                    invoice=instance,
                    description=line.get("description", ""),
                    quantity=line.get("quantity", 1),
                    unit_price=line.get("unit_price", 0),
                    vat_rate=line.get("vat_rate", 0),
                    amount=amount,
                    vat_amount=line_vat,
                )

            instance.subtotal = subtotal
            instance.vat_amount = vat_amount
            instance.total_amount = subtotal + vat_amount
            instance.save(
                update_fields=[
                    "subtotal",
                    "vat_amount",
                    "total_amount",
                    "updated_at",
                ]
            )

        return instance


class FixedAssetSerializer(SimpleSerializer):
    book_value = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )
    depreciation_method_display = serializers.CharField(
        source="get_depreciation_method_display",
        read_only=True,
    )
    depreciation_start_rule_display = serializers.CharField(
        source="get_depreciation_start_rule_display",
        read_only=True,
    )

    class Meta:
        model = FixedAsset
        fields = "__all__"

    def validate(self, attrs):
        purchase_cost = Decimal(
            attrs.get(
                "purchase_cost",
                getattr(self.instance, "purchase_cost", 0),
            )
            or 0
        )
        residual_value = Decimal(
            attrs.get(
                "residual_value",
                getattr(self.instance, "residual_value", 0),
            )
            or 0
        )
        useful_life_months = attrs.get(
            "useful_life_months",
            getattr(self.instance, "useful_life_months", 0),
        )
        method = attrs.get(
            "depreciation_method",
            getattr(self.instance, "depreciation_method", "STRAIGHT_LINE"),
        )
        production_capacity = attrs.get(
            "production_capacity",
            getattr(self.instance, "production_capacity", None),
        )
        start_rule = attrs.get(
            "depreciation_start_rule",
            getattr(self.instance, "depreciation_start_rule", "PURCHASE_DATE"),
        )
        start_date = attrs.get(
            "depreciation_start_date",
            getattr(self.instance, "depreciation_start_date", None),
        )
        purchase_date = attrs.get(
            "purchase_date",
            getattr(self.instance, "purchase_date", None),
        )

        errors = {}

        if purchase_cost <= 0:
            errors["purchase_cost"] = "Asset cost must be greater than zero."

        if residual_value < 0:
            errors["residual_value"] = "Residual value cannot be negative."
        elif residual_value >= purchase_cost:
            errors["residual_value"] = (
                "Residual value must be lower than the purchase cost."
            )

        if not useful_life_months or int(useful_life_months) <= 0:
            errors["useful_life_months"] = "Useful life must be greater than zero."

        if method == "UNITS_OF_PRODUCTION" and (
            production_capacity is None or Decimal(production_capacity or 0) <= 0
        ):
            errors["production_capacity"] = (
                "Production capacity is required for units-of-production."
            )

        if start_rule == "CUSTOM_DATE" and not start_date:
            errors["depreciation_start_date"] = (
                "Select a custom depreciation start date."
            )

        if start_date and purchase_date and start_date < purchase_date:
            errors["depreciation_start_date"] = (
                "Depreciation cannot start before the purchase date."
            )

        if errors:
            raise serializers.ValidationError(errors)

        if start_rule == "PURCHASE_DATE":
            attrs["depreciation_start_date"] = purchase_date

        return attrs


class TaxRateSerializer(SimpleSerializer):
    class Meta:
        model = TaxRate
        fields = "__all__"


class BudgetSerializer(SimpleSerializer):
    account_name = serializers.CharField(
        source="account.name",
        read_only=True,
    )

    account_code = serializers.CharField(
        source="account.code",
        read_only=True,
    )

    variance = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        read_only=True,
    )

    percent_used = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        read_only=True,
    )

    phasing_method_display = serializers.CharField(
        source="get_phasing_method_display",
        read_only=True,
    )

    notify_option_display = serializers.CharField(
        source="get_notify_option_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = Budget
        fields = "__all__"

    def validate(self, attrs):
        instance = self.instance

        branch = attrs.get(
            "branch",
            getattr(instance, "branch", None),
        )

        account = attrs.get(
            "account",
            getattr(instance, "account", None),
        )

        fiscal_year = attrs.get(
            "fiscal_year",
            getattr(instance, "fiscal_year", None),
        )

        period_from = attrs.get(
            "period_from",
            getattr(instance, "period_from", None),
        )

        period_to = attrs.get(
            "period_to",
            getattr(instance, "period_to", None),
        )

        budget_amount = Decimal(
            attrs.get(
                "budget_amount",
                getattr(instance, "budget_amount", 0),
            )
            or 0
        )

        phasing_method = attrs.get(
            "phasing_method",
            getattr(instance, "phasing_method", "EVEN"),
        )

        monthly_phasing = (
            attrs.get(
                "monthly_phasing",
                getattr(instance, "monthly_phasing", {}),
            )
            or {}
        )

        alert_threshold = int(
            attrs.get(
                "alert_threshold_percent",
                getattr(
                    instance,
                    "alert_threshold_percent",
                    90,
                ),
            )
            or 0
        )

        revision_number = int(
            attrs.get(
                "revision_number",
                getattr(instance, "revision_number", 1),
            )
            or 0
        )

        errors = {}

        if not branch:
            errors["branch"] = "Branch is required."

        if not account:
            errors["account"] = "Account is required."

        if (
            account
            and branch
            and account.branch_id
            not in (
                None,
                branch.id,
            )
        ):
            errors["account"] = "This account is not available for the selected branch."

        if budget_amount <= 0:
            errors["budget_amount"] = "Annual budget must be greater than zero."

        if period_from and period_to and period_to < period_from:
            errors["period_to"] = "Period end date cannot be before the start date."

        if fiscal_year and period_from:
            if period_from.year != int(fiscal_year):
                errors["period_from"] = (
                    "Period start date must be inside the fiscal year."
                )

        if fiscal_year and period_to:
            if period_to.year != int(fiscal_year):
                errors["period_to"] = "Period end date must be inside the fiscal year."

        if not 1 <= alert_threshold <= 100:
            errors["alert_threshold_percent"] = (
                "Alert threshold must be between 1 and 100."
            )

        if revision_number < 1:
            errors["revision_number"] = "Revision number must be at least 1."

        required_months = {
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        }

        supplied_months = set(monthly_phasing.keys())

        if supplied_months != required_months:
            missing = sorted(required_months - supplied_months)

            extra = sorted(supplied_months - required_months)

            message_parts = []

            if missing:
                message_parts.append("missing: " + ", ".join(missing))

            if extra:
                message_parts.append("unknown: " + ", ".join(extra))

            errors["monthly_phasing"] = (
                "Monthly phasing must contain exactly January "
                "through December"
                + (f" ({'; '.join(message_parts)})" if message_parts else "")
                + "."
            )
        else:
            normalized_monthly = {}

            for month, value in monthly_phasing.items():
                try:
                    amount = Decimal(str(value or 0))
                except Exception:
                    errors["monthly_phasing"] = f"Invalid amount for {month.upper()}."
                    break

                if amount < 0:
                    errors["monthly_phasing"] = (
                        f"{month.upper()} amount cannot be negative."
                    )
                    break

                normalized_monthly[month] = str(amount.quantize(Decimal("0.01")))

            if "monthly_phasing" not in errors:
                monthly_total = sum(
                    Decimal(value) for value in normalized_monthly.values()
                )

                if abs(monthly_total - budget_amount) > Decimal("0.01"):
                    errors["monthly_phasing"] = (
                        "Monthly figures must add up to the annual "
                        f"budget. Current total is {monthly_total}."
                    )
                else:
                    attrs["monthly_phasing"] = normalized_monthly

        if phasing_method not in {
            "EVEN",
            "SEASONAL",
            "CUSTOM",
        }:
            errors["phasing_method"] = "Invalid phasing method."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class AccountingPeriodSerializer(SimpleSerializer):
    class Meta:
        model = AccountingPeriod
        fields = "__all__"
        read_only_fields = ["closed_by", "closed_at"]


class BankTransactionSerializer(SimpleSerializer):
    bank_account_name = serializers.CharField(
        source="bank_account.account_name", read_only=True
    )

    class Meta:
        model = BankTransaction
        fields = "__all__"


class BankFundTransferSerializer(SimpleSerializer):
    from_account_name = serializers.CharField(
        source="from_account.account_name", read_only=True
    )
    to_account_name = serializers.CharField(
        source="to_account.account_name", read_only=True
    )

    class Meta:
        model = BankFundTransfer
        fields = "__all__"


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
        read_only_fields = ["bill", "amount", "vat_amount"]


class PayableBillSerializer(SimpleSerializer):
    lines = PayableBillLineSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    approver_name = serializers.SerializerMethodField()
    balance_due = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )

    class Meta:
        model = PayableBill
        fields = "__all__"
        read_only_fields = [
            "subtotal",
            "vat_amount",
            "withholding_tax_amount",
            "total_amount",
            "paid_amount",
            "approved_by",
            "approved_at",
        ]

    def get_approver_name(self, obj):
        return str(obj.approver) if obj.approver else None

    def _totals(self, lines, rate, apply_tds):
        subtotal = Decimal("0")
        vat = Decimal("0")
        for line in lines:
            amount = Decimal(str(line.get("quantity") or 0)) * Decimal(
                str(line.get("unit_price") or 0)
            )
            line_vat = amount * Decimal(str(line.get("vat_rate") or 0)) / Decimal("100")
            subtotal += amount
            vat += line_vat
        tds = (
            (subtotal * Decimal(str(rate or 0)) / Decimal("100"))
            if apply_tds
            else Decimal("0")
        )
        return subtotal, vat, tds, subtotal + vat - tds

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        subtotal, vat, tds, total = self._totals(
            lines,
            validated_data.get("withholding_tax_rate"),
            validated_data.get("apply_withholding_tax"),
        )
        bill = PayableBill.objects.create(
            **validated_data,
            subtotal=subtotal,
            vat_amount=vat,
            withholding_tax_amount=tds,
            total_amount=total,
        )
        for line in lines:
            amount = Decimal(str(line.get("quantity") or 0)) * Decimal(
                str(line.get("unit_price") or 0)
            )
            lv = amount * Decimal(str(line.get("vat_rate") or 0)) / Decimal("100")
            PayableBillLine.objects.create(
                bill=bill,
                description=line.get("description", ""),
                quantity=line.get("quantity", 1),
                unit_price=line.get("unit_price", 0),
                vat_rate=line.get("vat_rate", 0),
                amount=amount,
                vat_amount=lv,
            )
        return bill


class PayablePaymentSerializer(SimpleSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    bill_number = serializers.CharField(source="bill.bill_number", read_only=True)

    class Meta:
        model = PayablePayment
        fields = "__all__"
