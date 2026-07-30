from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

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
    LedgerEntry,
    ReceivableInvoice,
    ReceivableReceipt,
    TaxRate,
    BankTransaction,
    BankFundTransfer,
    AssetDepreciationRun,
    AssetDisposal,
    PayableBill,
    PayablePayment,
)
from .serializers import (
    AccountingPeriodSerializer,
    BankAccountSerializer,
    BudgetSerializer,
    CashRegisterSerializer,
    ChartOfAccountSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    FixedAssetSerializer,
    JournalEntrySerializer,
    LedgerEntrySerializer,
    ReceivableInvoiceSerializer,
    ReceivableReceiptSerializer,
    TaxRateSerializer,
    BankTransactionSerializer,
    BankFundTransferSerializer,
    AssetDepreciationRunSerializer,
    AssetDisposalSerializer,
    PayableBillSerializer,
    PayablePaymentSerializer,
)


class GenericViewSet(ModelViewSet):
    search_fields = []
    ordering_fields = "__all__"

    def perform_create(self, serializer):
        kwargs = {}
        if hasattr(serializer.Meta.model, "created_by"):
            kwargs["created_by"] = self.request.user
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        kwargs = {}
        if hasattr(serializer.Meta.model, "updated_by"):
            kwargs["updated_by"] = self.request.user
        serializer.save(**kwargs)


class ExpenseViewSet(GenericViewSet):
    queryset = Expense.objects.select_related("branch", "category", "supplier")
    serializer_class = ExpenseSerializer
    filterset_fields = ["branch", "category", "expense_date"]
    search_fields = ["expense_number", "notes"]


class ExpenseCategoryViewSet(GenericViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer


class CashRegisterViewSet(GenericViewSet):
    queryset = CashRegister.objects.select_related("branch")
    serializer_class = CashRegisterSerializer
    filterset_fields = ["branch", "status", "register_date"]


class BankAccountViewSet(GenericViewSet):
    queryset = BankAccount.objects.select_related("branch")
    serializer_class = BankAccountSerializer
    filterset_fields = ["branch", "is_active"]
    search_fields = [
        "bank_name",
        "account_name",
        "account_number",
        "iban_number",
    ]


class ChartOfAccountViewSet(GenericViewSet):
    queryset = ChartOfAccount.objects.all()
    serializer_class = ChartOfAccountSerializer
    filterset_fields = [
        "branch",
        "account_type",
        "sub_type",
        "normal_balance",
        "tax_treatment",
        "is_active",
        "lock_from_posting",
        "parent",
    ]
    search_fields = ["code", "name", "notes"]

    def get_queryset(self):
        queryset = (
            ChartOfAccount.objects.select_related("branch", "parent")
            .annotate(children_count=Count("children"))
            .order_by("code")
        )
        branch = self.request.query_params.get("branch")
        available = self.request.query_params.get("available_for_branch")

        if available:
            queryset = queryset.filter(Q(branch_id=available) | Q(branch__isnull=True))
        elif branch:
            queryset = queryset.filter(Q(branch_id=branch) | Q(branch__isnull=True))

        return queryset

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()
        if account.children.exists():
            return Response(
                {
                    "detail": (
                        "Remove or reassign child accounts before deleting "
                        "this account."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if account.journalline_set.exists() or account.ledgerentry_set.exists():
            return Response(
                {
                    "detail": (
                        "Accounts with journal or ledger activity cannot be "
                        "deleted. Mark the account inactive instead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="grouped-summary")
    def grouped_summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        labels = dict(ChartOfAccount.TYPES)
        prefixes = {
            "ASSET": "1xxxx",
            "LIABILITY": "2xxxx",
            "EQUITY": "3xxxx",
            "INCOME": "4xxxx",
            "EXPENSE": "5xxxx",
        }
        groups = []

        for account_type, _ in ChartOfAccount.TYPES:
            accounts = queryset.filter(account_type=account_type)
            groups.append(
                {
                    "account_type": account_type,
                    "label": labels[account_type],
                    "prefix": prefixes[account_type],
                    "balance": str(
                        accounts.aggregate(value=Sum("current_balance"))["value"] or 0
                    ),
                    "accounts": self.get_serializer(
                        accounts,
                        many=True,
                    ).data,
                }
            )

        return Response(groups)


class JournalEntryViewSet(GenericViewSet):
    queryset = (
        JournalEntry.objects.select_related(
            "branch",
            "approver",
            "approved_by",
            "posted_by",
        )
        .prefetch_related("lines__account")
        .order_by("-entry_date", "-id")
    )
    serializer_class = JournalEntrySerializer
    filterset_fields = [
        "branch",
        "status",
        "entry_date",
        "voucher_type",
    ]
    search_fields = [
        "entry_number",
        "reference",
        "description",
    ]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        journal = self.get_object()
        if journal.status not in ["DRAFT", "PENDING_APPROVAL"]:
            return Response(
                {"detail": "Only draft journals can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        journal.status = "APPROVED"
        journal.approved_by = request.user
        journal.approved_at = timezone.now()
        journal.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(journal).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def post(self, request, pk=None):
        journal = self.get_object()

        if journal.status == "POSTED":
            return Response(
                {"detail": "This journal is already posted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if journal.status == "REVERSED":
            return Response(
                {"detail": "A reversed journal cannot be posted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if journal.total_debit != journal.total_credit:
            return Response(
                {"detail": "Journal is not balanced."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        restricted = [
            line.account
            for line in journal.lines.select_related("account")
            if not line.account.is_active or line.account.lock_from_posting
        ]
        if restricted:
            return Response(
                {
                    "detail": (
                        "Posting is blocked for: "
                        + ", ".join(str(item) for item in restricted)
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        for line in journal.lines.select_related("account"):
            account = line.account
            movement = Decimal(line.debit or 0) - Decimal(line.credit or 0)
            if account.normal_balance == "CREDIT":
                movement = Decimal(line.credit or 0) - Decimal(line.debit or 0)

            account.current_balance = Decimal(account.current_balance or 0) + movement
            account.save(update_fields=["current_balance", "updated_at"])

            LedgerEntry.objects.create(
                entry_number=f"{journal.entry_number}-{line.id}",
                branch=journal.branch,
                account=account,
                ledger_type=account.account_type,
                transaction_type="JOURNAL",
                reference_type="JournalEntry",
                reference_id=str(journal.id),
                debit_amount=line.debit,
                credit_amount=line.credit,
                balance=account.current_balance,
                transaction_date=journal.entry_date,
                remarks=line.description or journal.description,
            )

        journal.status = "POSTED"
        journal.posted_by = request.user
        journal.posted_at = timezone.now()
        journal.save(
            update_fields=[
                "status",
                "posted_by",
                "posted_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(journal).data)


class LedgerViewSet(GenericViewSet):
    queryset = LedgerEntry.objects.select_related(
        "branch",
        "account",
        "customer",
        "supplier",
    ).order_by("transaction_date", "id")
    serializer_class = LedgerEntrySerializer
    filterset_fields = [
        "branch",
        "account",
        "ledger_type",
        "customer",
        "supplier",
        "transaction_type",
    ]
    search_fields = [
        "entry_number",
        "reference_id",
        "remarks",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if date_from:
            queryset = queryset.filter(transaction_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(transaction_date__lte=date_to)

        return queryset

    @action(detail=False, methods=["get"], url_path="account-summary")
    def account_summary(self, request):
        account_id = request.query_params.get("account")
        if not account_id:
            return Response(
                {"detail": "Account is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account = ChartOfAccount.objects.get(pk=account_id)
        queryset = self.filter_queryset(self.get_queryset()).filter(account=account)
        opening = Decimal(account.opening_balance or 0)
        running = opening
        rows = []

        for entry in queryset:
            if account.normal_balance == "CREDIT":
                running += Decimal(entry.credit_amount or 0)
                running -= Decimal(entry.debit_amount or 0)
            else:
                running += Decimal(entry.debit_amount or 0)
                running -= Decimal(entry.credit_amount or 0)

            rows.append(
                {
                    **self.get_serializer(entry).data,
                    "running_balance": str(running),
                }
            )

        return Response(
            {
                "account": ChartOfAccountSerializer(account).data,
                "opening_balance": str(opening),
                "closing_balance": str(running),
                "total_debit": str(
                    queryset.aggregate(value=Sum("debit_amount"))["value"] or 0
                ),
                "total_credit": str(
                    queryset.aggregate(value=Sum("credit_amount"))["value"] or 0
                ),
                "entries": rows,
            }
        )


class ReceivableInvoiceViewSet(GenericViewSet):
    queryset = (
        ReceivableInvoice.objects.select_related("branch", "customer")
        .prefetch_related("lines", "receipts")
        .order_by("-invoice_date", "-id")
    )
    serializer_class = ReceivableInvoiceSerializer
    filterset_fields = [
        "branch",
        "customer",
        "status",
        "invoice_date",
        "due_date",
    ]
    search_fields = [
        "invoice_number",
        "customer__name",
        "notes",
    ]

    @action(detail=True, methods=["post"], url_path="mark-sent")
    def mark_sent(self, request, pk=None):
        invoice = self.get_object()
        invoice.status = "SENT"
        invoice.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(invoice).data)

    @action(detail=False, methods=["get"], url_path="aging-summary")
    def aging_summary(self, request):
        today = timezone.localdate()
        queryset = self.filter_queryset(self.get_queryset()).exclude(
            status__in=["PAID", "CANCELLED", "WRITTEN_OFF"]
        )

        buckets = {
            "current": Decimal("0"),
            "days_1_30": Decimal("0"),
            "days_31_60": Decimal("0"),
            "days_61_90": Decimal("0"),
            "days_90_plus": Decimal("0"),
        }

        for invoice in queryset:
            value = invoice.balance_due
            age = (today - invoice.due_date).days
            if age <= 0:
                buckets["current"] += value
            elif age <= 30:
                buckets["days_1_30"] += value
            elif age <= 60:
                buckets["days_31_60"] += value
            elif age <= 90:
                buckets["days_61_90"] += value
            else:
                buckets["days_90_plus"] += value

        return Response({key: str(value) for key, value in buckets.items()})


class ReceivableReceiptViewSet(GenericViewSet):
    queryset = ReceivableReceipt.objects.select_related(
        "branch", "invoice", "customer"
    ).order_by("-receipt_date", "-id")
    serializer_class = ReceivableReceiptSerializer
    filterset_fields = [
        "branch",
        "invoice",
        "customer",
        "receipt_date",
        "payment_method",
    ]
    search_fields = [
        "receipt_number",
        "invoice__invoice_number",
        "customer__name",
        "reference",
    ]

    @transaction.atomic
    def perform_create(self, serializer):
        receipt = serializer.save()
        invoice = receipt.invoice

        if receipt.customer_id != invoice.customer_id:
            raise ValueError("Receipt customer must match the invoice customer.")

        invoice.paid_amount = Decimal(invoice.paid_amount or 0) + Decimal(
            receipt.amount or 0
        )

        if invoice.paid_amount >= invoice.total_amount:
            invoice.status = "PAID"
        elif invoice.paid_amount > 0:
            invoice.status = "PARTIALLY_PAID"

        invoice.save(
            update_fields=[
                "paid_amount",
                "status",
                "updated_at",
            ]
        )


class FixedAssetViewSet(GenericViewSet):
    queryset = FixedAsset.objects.select_related("branch")
    serializer_class = FixedAssetSerializer


class TaxRateViewSet(GenericViewSet):
    queryset = TaxRate.objects.select_related("branch")
    serializer_class = TaxRateSerializer


class BudgetViewSet(GenericViewSet):
    queryset = Budget.objects.select_related("branch", "account").order_by(
        "-fiscal_year",
        "account__code",
        "revision_number",
        "id",
    )
    serializer_class = BudgetSerializer
    filterset_fields = [
        "branch",
        "fiscal_year",
        "account",
        "status",
        "phasing_method",
        "department_name",
        "cost_centre",
    ]
    search_fields = [
        "name",
        "account__code",
        "account__name",
        "branch__branch_name",
        "department_name",
        "cost_centre",
        "revision_note",
    ]
    ordering_fields = [
        "fiscal_year",
        "account__code",
        "budget_amount",
        "actual_amount",
        "revision_number",
        "created_at",
        "updated_at",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        branch = self.request.query_params.get("branch")
        fiscal_year = self.request.query_params.get("fiscal_year")

        if branch not in (None, "", "all"):
            queryset = queryset.filter(branch_id=branch)

        if fiscal_year:
            queryset = queryset.filter(fiscal_year=fiscal_year)

        return queryset

    @action(detail=False, methods=["get"], url_path="year-summary")
    def year_summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        totals = queryset.aggregate(
            total_budget=Sum("budget_amount"),
            total_actual=Sum("actual_amount"),
        )
        total_budget = totals["total_budget"] or Decimal("0")
        total_actual = totals["total_actual"] or Decimal("0")

        return Response(
            {
                "fiscal_year": request.query_params.get("fiscal_year"),
                "branch": request.query_params.get("branch"),
                "total_budget": str(total_budget),
                "total_actual": str(total_actual),
                "variance": str(total_budget - total_actual),
                "rows": self.get_serializer(queryset, many=True).data,
            }
        )


class AccountingPeriodViewSet(GenericViewSet):
    queryset = AccountingPeriod.objects.select_related("branch")
    serializer_class = AccountingPeriodSerializer


class AccountingDashboardViewSet(GenericViewSet):
    queryset = ChartOfAccount.objects.none()
    serializer_class = ChartOfAccountSerializer


class BankTransactionViewSet(GenericViewSet):
    queryset = BankTransaction.objects.select_related(
        "branch", "bank_account"
    ).order_by("transaction_date", "id")
    serializer_class = BankTransactionSerializer
    filterset_fields = [
        "branch",
        "bank_account",
        "transaction_type",
        "reconciliation_status",
    ]
    search_fields = ["voucher_number", "particulars", "reference"]


class BankFundTransferViewSet(GenericViewSet):
    queryset = BankFundTransfer.objects.select_related(
        "branch", "from_account", "to_account", "journal"
    )
    serializer_class = BankFundTransferSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        transfer = serializer.save()
        if transfer.from_account_id == transfer.to_account_id:
            raise ValueError("Source and destination accounts must differ.")
        if transfer.from_account.current_balance < transfer.amount:
            raise ValueError("Insufficient balance in source account.")
        transfer.from_account.current_balance -= transfer.amount
        transfer.from_account.save(update_fields=["current_balance", "updated_at"])
        transfer.to_account.current_balance += transfer.amount
        transfer.to_account.save(update_fields=["current_balance", "updated_at"])


class AssetDepreciationRunViewSet(GenericViewSet):
    queryset = AssetDepreciationRun.objects.select_related(
        "branch", "journal"
    ).prefetch_related("lines__asset")
    serializer_class = AssetDepreciationRunSerializer
    filterset_fields = ["period", "branch", "status"]

    @action(detail=False, methods=["post"], url_path="calculate")
    @transaction.atomic
    def calculate(self, request):
        period = request.data.get("period")
        branch = request.data.get("branch")
        run_date = request.data.get("run_date") or timezone.localdate()
        assets = FixedAsset.objects.filter(status="ACTIVE")
        if branch:
            assets = assets.filter(branch_id=branch)
        run = AssetDepreciationRun.objects.create(
            period=period,
            branch_id=branch or None,
            run_date=run_date,
            auto_post_journal=request.data.get("auto_post_journal", True),
            lock_period_after_posting=request.data.get(
                "lock_period_after_posting", True
            ),
        )
        total = Decimal("0")
        for asset in assets:
            depreciable = max(
                Decimal("0"),
                Decimal(asset.purchase_cost) - Decimal(asset.residual_value),
            )
            monthly = depreciable / Decimal(asset.useful_life_months or 1)
            monthly = min(monthly, Decimal(asset.book_value))
            if monthly <= 0:
                continue
            AssetDepreciationLine.objects.create(
                run=run,
                asset=asset,
                opening_book_value=asset.book_value,
                depreciation_amount=monthly,
                closing_book_value=Decimal(asset.book_value) - monthly,
            )
            asset.accumulated_depreciation += monthly
            asset.save(update_fields=["accumulated_depreciation", "updated_at"])
            total += monthly
        run.total_depreciation = total
        run.status = "POSTED" if run.auto_post_journal else "DRAFT"
        run.save(update_fields=["total_depreciation", "status", "updated_at"])
        return Response(self.get_serializer(run).data, status=201)


class AssetDisposalViewSet(GenericViewSet):
    queryset = AssetDisposal.objects.select_related("branch", "asset", "journal")
    serializer_class = AssetDisposalSerializer
    filterset_fields = ["branch", "disposal_method", "disposal_date"]
    search_fields = [
        "asset__asset_code",
        "asset__name",
        "buyer_or_recipient",
        "reference",
    ]


class PayableBillViewSet(GenericViewSet):
    queryset = PayableBill.objects.select_related(
        "branch", "supplier", "approver", "approved_by"
    ).prefetch_related("lines", "payments")
    serializer_class = PayableBillSerializer
    filterset_fields = ["branch", "supplier", "status", "bill_date", "due_date"]
    search_fields = ["bill_number", "supplier_invoice_number", "supplier__name"]

    @action(detail=True, methods=["post"], url_path="submit-approval")
    def submit_approval(self, request, pk=None):
        bill = self.get_object()
        bill.status = "PENDING_APPROVAL"
        bill.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(bill).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        bill = self.get_object()
        bill.status = "APPROVED"
        bill.approved_by = request.user
        bill.approved_at = timezone.now()
        bill.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return Response(self.get_serializer(bill).data)

    @action(detail=False, methods=["get"], url_path="aging-summary")
    def aging_summary(self, request):
        today = timezone.localdate()
        qs = self.filter_queryset(self.get_queryset()).exclude(
            status__in=["PAID", "CANCELLED"]
        )
        b = {
            "current": Decimal("0"),
            "days_1_30": Decimal("0"),
            "days_31_60": Decimal("0"),
            "days_61_90": Decimal("0"),
            "days_90_plus": Decimal("0"),
        }
        for bill in qs:
            age = (today - bill.due_date).days
            v = bill.balance_due
            key = (
                "current"
                if age <= 0
                else (
                    "days_1_30"
                    if age <= 30
                    else (
                        "days_31_60"
                        if age <= 60
                        else "days_61_90" if age <= 90 else "days_90_plus"
                    )
                )
            )
            b[key] += v
        return Response({k: str(v) for k, v in b.items()})


class PayablePaymentViewSet(GenericViewSet):
    queryset = PayablePayment.objects.select_related("branch", "bill", "supplier")
    serializer_class = PayablePaymentSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        p = serializer.save()
        bill = p.bill
        bill.paid_amount += p.amount
        bill.status = (
            "PAID" if bill.paid_amount >= bill.total_amount else "PARTIALLY_PAID"
        )
        bill.save(update_fields=["paid_amount", "status", "updated_at"])


# -----------------------------------------------------------------------------
# Reporting, VAT, period close, and branch consolidation endpoints
# -----------------------------------------------------------------------------


def _branch_id(request):
    value = request.query_params.get("branch")
    return int(value) if value not in (None, "", "all") else None


def _accounts(request):
    queryset = ChartOfAccount.objects.select_related("branch").filter(is_active=True)
    branch_id = _branch_id(request)
    if branch_id:
        queryset = queryset.filter(Q(branch_id=branch_id) | Q(branch__isnull=True))
    return queryset.order_by("code")


def _account_row(account):
    return {
        "id": account.id,
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type,
        "sub_type": account.sub_type,
        "normal_balance": account.normal_balance,
        "branch": account.branch_id,
        "branch_name": account.branch.branch_name if account.branch else "All branches",
        "current_balance": str(account.current_balance or 0),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vat_summary(request):
    branch_id = _branch_id(request)
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")

    sales = ReceivableInvoice.objects.select_related("branch", "customer").exclude(
        status__in=["CANCELLED", "WRITTEN_OFF"]
    )
    purchases = PayableBill.objects.select_related("branch", "supplier").exclude(
        status="CANCELLED"
    )

    if branch_id:
        sales = sales.filter(branch_id=branch_id)
        purchases = purchases.filter(branch_id=branch_id)
    if date_from:
        sales = sales.filter(invoice_date__gte=date_from)
        purchases = purchases.filter(bill_date__gte=date_from)
    if date_to:
        sales = sales.filter(invoice_date__lte=date_to)
        purchases = purchases.filter(bill_date__lte=date_to)

    taxable_sales = sales.aggregate(value=Sum("subtotal"))["value"] or Decimal("0")
    output_vat = sales.aggregate(value=Sum("vat_amount"))["value"] or Decimal("0")
    taxable_purchases = purchases.aggregate(value=Sum("subtotal"))["value"] or Decimal(
        "0"
    )
    input_vat = purchases.aggregate(value=Sum("vat_amount"))["value"] or Decimal("0")

    transactions = []
    for invoice in sales.order_by("-invoice_date", "-id")[:500]:
        transactions.append(
            {
                "id": f"sale-{invoice.id}",
                "transaction_date": invoice.invoice_date,
                "document_number": invoice.invoice_number,
                "transaction_type": "OUTPUT",
                "transaction_type_display": "Output VAT",
                "branch_name": invoice.branch.branch_name,
                "taxable_value": str(invoice.subtotal),
                "vat_amount": str(invoice.vat_amount),
                "description": invoice.customer.name,
            }
        )
    for bill in purchases.order_by("-bill_date", "-id")[:500]:
        transactions.append(
            {
                "id": f"purchase-{bill.id}",
                "transaction_date": bill.bill_date,
                "document_number": bill.bill_number,
                "transaction_type": "INPUT",
                "transaction_type_display": "Input VAT",
                "branch_name": bill.branch.branch_name,
                "taxable_value": str(bill.subtotal),
                "vat_amount": str(bill.vat_amount),
                "description": bill.supplier.name,
            }
        )

    transactions.sort(key=lambda item: str(item["transaction_date"]), reverse=True)

    return Response(
        {
            "taxable_sales": str(taxable_sales),
            "output_vat": str(output_vat),
            "taxable_purchases": str(taxable_purchases),
            "input_vat": str(input_vat),
            "net_vat_payable": str(output_vat - input_vat),
            "transactions": transactions,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def trial_balance(request):
    rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for account in _accounts(request):
        balance = Decimal(account.current_balance or 0)
        debit = Decimal("0")
        credit = Decimal("0")
        if account.normal_balance == "DEBIT":
            debit = balance if balance >= 0 else Decimal("0")
            credit = abs(balance) if balance < 0 else Decimal("0")
        else:
            credit = balance if balance >= 0 else Decimal("0")
            debit = abs(balance) if balance < 0 else Decimal("0")
        total_debit += debit
        total_credit += credit
        rows.append(
            {**_account_row(account), "debit": str(debit), "credit": str(credit)}
        )

    return Response(
        {
            "rows": rows,
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "balanced": total_debit == total_credit,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def income_statement(request):
    accounts = _accounts(request)
    revenue = list(accounts.filter(account_type="INCOME"))
    expenses = list(accounts.filter(account_type="EXPENSE"))
    total_revenue = sum(
        (Decimal(a.current_balance or 0) for a in revenue), Decimal("0")
    )
    total_expenses = sum(
        (Decimal(a.current_balance or 0) for a in expenses), Decimal("0")
    )
    return Response(
        {
            "revenue": [_account_row(a) for a in revenue],
            "expenses": [_account_row(a) for a in expenses],
            "total_revenue": str(total_revenue),
            "total_expenses": str(total_expenses),
            "net_profit": str(total_revenue - total_expenses),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def balance_sheet(request):
    accounts = _accounts(request)
    assets = list(accounts.filter(account_type="ASSET"))
    liabilities = list(accounts.filter(account_type="LIABILITY"))
    equity = list(accounts.filter(account_type="EQUITY"))
    return Response(
        {
            "assets": [_account_row(a) for a in assets],
            "liabilities": [_account_row(a) for a in liabilities],
            "equity": [_account_row(a) for a in equity],
            "total_assets": str(
                sum((Decimal(a.current_balance or 0) for a in assets), Decimal("0"))
            ),
            "total_liabilities": str(
                sum(
                    (Decimal(a.current_balance or 0) for a in liabilities), Decimal("0")
                )
            ),
            "total_equity": str(
                sum((Decimal(a.current_balance or 0) for a in equity), Decimal("0"))
            ),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cash_flow(request):
    queryset = LedgerEntry.objects.select_related("account", "branch").filter(
        Q(account__sub_type="CASH") | Q(account__sub_type="BANK")
    )
    branch_id = _branch_id(request)
    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)
    if request.query_params.get("date_from"):
        queryset = queryset.filter(
            transaction_date__gte=request.query_params["date_from"]
        )
    if request.query_params.get("date_to"):
        queryset = queryset.filter(
            transaction_date__lte=request.query_params["date_to"]
        )

    receipts = queryset.aggregate(value=Sum("debit_amount"))["value"] or Decimal("0")
    payments = queryset.aggregate(value=Sum("credit_amount"))["value"] or Decimal("0")
    rows = [
        {
            "id": entry.id,
            "transaction_date": entry.transaction_date,
            "entry_number": entry.entry_number,
            "remarks": entry.remarks,
            "debit_amount": str(entry.debit_amount),
            "credit_amount": str(entry.credit_amount),
        }
        for entry in queryset.order_by("transaction_date", "id")
    ]
    return Response(
        {
            "cash_receipts": str(receipts),
            "cash_payments": str(payments),
            "net_cash_flow": str(receipts - payments),
            "rows": rows,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def changes_in_equity(request):
    equity = list(_accounts(request).filter(account_type="EQUITY"))
    return Response(
        {
            "rows": [_account_row(a) for a in equity],
            "closing_equity": str(
                sum((Decimal(a.current_balance or 0) for a in equity), Decimal("0"))
            ),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def branch_consolidation(request):
    from apps.branches.models import Branch

    branches = list(Branch.objects.all().order_by("id"))
    rows = []
    definitions = [
        ("Revenue", "INCOME", None),
        ("Cost of Goods Sold", "EXPENSE", "COST_OF_GOODS_SOLD"),
        ("Operating Expenses", "EXPENSE", "OTHER"),
    ]

    for label, account_type, mode in definitions:
        values = {}
        total = Decimal("0")
        for branch in branches:
            qs = ChartOfAccount.objects.filter(
                branch=branch, account_type=account_type, is_active=True
            )
            if mode == "COST_OF_GOODS_SOLD":
                qs = qs.filter(sub_type="COST_OF_GOODS_SOLD")
            elif mode == "OTHER":
                qs = qs.exclude(sub_type="COST_OF_GOODS_SOLD")
            value = qs.aggregate(value=Sum("current_balance"))["value"] or Decimal("0")
            values[str(branch.id)] = str(value)
            total += value
        rows.append(
            {
                "metric": label,
                "branches": values,
                "elimination": "0",
                "consolidated": str(total),
            }
        )

    revenue = Decimal(rows[0]["consolidated"])
    cogs = Decimal(rows[1]["consolidated"])
    operating = Decimal(rows[2]["consolidated"])
    rows.append(
        {
            "metric": "Net Profit",
            "branches": {},
            "elimination": "0",
            "consolidated": str(revenue - cogs - operating),
        }
    )

    return Response(
        {
            "branches": [
                {
                    "id": branch.id,
                    "name": branch.branch_name,
                    "code": getattr(branch, "branch_code", ""),
                }
                for branch in branches
            ],
            "rows": rows,
        }
    )


DEFAULT_CLOSE_TASKS = [
    (1, "Post all sales and purchase invoices for the period", "Accounts Team"),
    (2, "Bank reconciliation completed for all accounts", "Finance Manager"),
    (3, "Depreciation run for the month", "System"),
    (4, "Accrue salaries and recurring expenses", "Accounts Team"),
    (5, "Review and clear suspense or unmatched entries", "Finance Manager"),
    (6, "Prepare and review Trial Balance", "Finance Manager"),
    (7, "Lock period and roll forward", "Owner Approval"),
]


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def period_close(request):
    if request.method == "POST":
        branch_id = request.data.get("branch") or None
        period = AccountingPeriod.objects.create(
            branch_id=branch_id,
            name=request.data["name"],
            start_date=request.data["start_date"],
            end_date=request.data["end_date"],
            status="OPEN",
            notes=request.data.get("notes", ""),
        )
        return Response({"id": period.id}, status=status.HTTP_201_CREATED)

    branch_id = _branch_id(request)
    queryset = AccountingPeriod.objects.select_related("branch", "closed_by").order_by(
        "-start_date", "-id"
    )
    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)
    rows = []
    for period in queryset[:100]:
        completed = []
        if period.notes.startswith("CHECKLIST:"):
            completed = [
                int(value)
                for value in period.notes.replace("CHECKLIST:", "").split(",")
                if value
            ]
        rows.append(
            {
                "id": period.id,
                "name": period.name,
                "branch": period.branch_id,
                "branch_name": (
                    period.branch.branch_name if period.branch else "All branches"
                ),
                "start_date": period.start_date,
                "end_date": period.end_date,
                "status": period.status,
                "status_display": period.get_status_display(),
                "completed_task_ids": completed,
                "close_tasks": [
                    {
                        "id": seq,
                        "sequence": seq,
                        "title": title,
                        "responsible_role_display": role,
                        "is_completed": seq in completed,
                    }
                    for seq, title, role in DEFAULT_CLOSE_TASKS
                ],
            }
        )
    return Response(rows)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def period_task_toggle(request, period_id, task_id):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    completed = set()
    if period.notes.startswith("CHECKLIST:"):
        completed = {
            int(value)
            for value in period.notes.replace("CHECKLIST:", "").split(",")
            if value
        }
    if request.data.get("completed", True):
        completed.add(task_id)
    else:
        completed.discard(task_id)
    period.notes = "CHECKLIST:" + ",".join(str(value) for value in sorted(completed))
    period.save(update_fields=["notes", "updated_at"])
    return Response({"completed_task_ids": sorted(completed)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def period_action(request, period_id, action):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    if action == "close":
        completed = set()
        if period.notes.startswith("CHECKLIST:"):
            completed = {
                int(value)
                for value in period.notes.replace("CHECKLIST:", "").split(",")
                if value
            }
        if len(completed) < len(DEFAULT_CLOSE_TASKS):
            return Response(
                {"detail": "Complete all checklist items before closing."}, status=400
            )
        period.status = "CLOSED"
        period.closed_by = request.user
        period.closed_at = timezone.now()
    elif action == "lock":
        if period.status != "CLOSED":
            return Response(
                {"detail": "Close the period before locking it."}, status=400
            )
        period.status = "LOCKED"
    else:
        return Response({"detail": "Unsupported action."}, status=400)
    period.save()
    return Response({"status": period.status})
