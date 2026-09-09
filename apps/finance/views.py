from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
import csv
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

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
    JournalEntry,
    JournalLine,
    JournalAttachment,
    LedgerEntry,
    ReceivableInvoice,
    ReceivableInvoiceAttachment,
    ReceivableReceipt,
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
    PayableBillAttachment,
    PayablePayment,
    FixedAssetAttachment,
    FixedAssetDepreciation,
    FixedAssetDisposal,
    FixedAssetTransfer,
    FixedAssetMaintenance,
)
from .serializers import (
    AccountingPeriodSerializer,
    BankAccountSerializer,
    BudgetSerializer,
    BudgetRevisionSerializer,
    CashRegisterSerializer,
    ChartOfAccountSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    FixedAssetSerializer,
    JournalEntrySerializer,
    JournalAttachmentSerializer,
    LedgerEntrySerializer,
    ReceivableInvoiceSerializer,
    ReceivableInvoiceAttachmentSerializer,
    ReceivableReceiptSerializer,
    TaxRateSerializer,
    VatSettingsSerializer,
    VatReturnSerializer,
    BankTransactionSerializer,
    BankFundTransferSerializer,
    AssetDepreciationRunSerializer,
    AssetDisposalSerializer,
    PayableBillSerializer,
    PayableBillAttachmentSerializer,
    PayablePaymentSerializer,
    FixedAssetAttachmentSerializer,
    FixedAssetDepreciationSerializer,
    FixedAssetDisposalSerializer,
    FixedAssetTransferSerializer,
    FixedAssetMaintenanceSerializer,
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

    def destroy(self, request, *args, **kwargs):
        register = self.get_object()

        # A cash register is an accounting record. Once it has been referenced
        # by any transaction, keep it for audit/history instead of allowing it
        # to be deleted. This explicitly covers relations that use SET_NULL as
        # well as the SupplierPayment relation that already uses PROTECT.
        from apps.purchases.models import PurchaseExpense, SupplierPayment
        from apps.sales.models import SalesPayment

        usage = {
            "supplier payments": SupplierPayment.objects.filter(
                cash_register=register
            ).count(),
            "purchase expenses": PurchaseExpense.objects.filter(
                cash_register=register
            ).count(),
            "sales payments": SalesPayment.objects.filter(
                cash_register=register
            ).count(),
        }
        used_by = [
            f"{count} {label}"
            for label, count in usage.items()
            if count
        ]

        if used_by:
            return Response(
                {
                    "detail": (
                        "This cash register cannot be deleted because it has "
                        "already been used in " + ", ".join(used_by) + ". "
                        "Keep the register for accounting history and close it "
                        "instead."
                    ),
                    "usage": usage,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().destroy(request, *args, **kwargs)


class BankAccountViewSet(GenericViewSet):
    queryset = BankAccount.objects.select_related(
        "branch",
        "chart_account",
    ).order_by("account_name")

    serializer_class = BankAccountSerializer

    filterset_fields = [
        "branch",
        "account_type",
        "currency",
        "is_active",
    ]

    search_fields = [
        "bank_name",
        "account_name",
        "account_number",
        "iban_number",
    ]

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        bank_balance = queryset.filter(
            account_type="BANK",
            is_active=True,
        ).aggregate(
            value=Sum("current_balance")
        )["value"] or Decimal("0")

        cash_balance = queryset.filter(
            account_type="CASH",
            is_active=True,
        ).aggregate(
            value=Sum("current_balance")
        )["value"] or Decimal("0")

        transactions = BankTransaction.objects.filter(
            bank_account__in=queryset,
            reconciliation_status="UNMATCHED",
        )

        unreconciled_amount = sum(
            (
                max(
                    Decimal(item.receipt_amount or 0),
                    Decimal(item.payment_amount or 0),
                )
                for item in transactions
            ),
            Decimal("0"),
        )

        return Response(
            {
                "bank_balance": str(bank_balance),
                "cash_balance": str(cash_balance),
                "unreconciled_amount": str(unreconciled_amount),
                "active_accounts": (queryset.filter(is_active=True).count()),
            }
        )


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
            "rejected_by",
            "posted_by",
            "created_by",
            "updated_by",
            "reversed_from",
        )
        .prefetch_related(
            "lines__account",
            "attachments__uploaded_by",
        )
        .order_by("-entry_date", "-id")
    )
    serializer_class = JournalEntrySerializer
    filterset_fields = [
        "branch",
        "status",
        "entry_date",
        "voucher_type",
        "source",
        "approval_priority",
    ]
    search_fields = [
        "entry_number",
        "reference",
        "description",
        "lines__description",
        "lines__account__code",
        "lines__account__name",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if date_from:
            queryset = queryset.filter(entry_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(entry_date__lte=date_to)

        return queryset.distinct()

    def perform_destroy(self, instance):
        if instance.status not in ["DRAFT", "REJECTED"]:
            raise ValueError("Only Draft or Rejected journals can be deleted.")
        instance.delete()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        return Response(
            {
                "draft": queryset.filter(status="DRAFT").count(),
                "pending_approval": queryset.filter(status="PENDING_APPROVAL").count(),
                "posted": queryset.filter(status="POSTED").count(),
                "rejected": queryset.filter(status="REJECTED").count(),
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="journal-register.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "JV No.",
                "Posting Date",
                "Document Date",
                "Type",
                "Source",
                "Narration",
                "Debit Total",
                "Credit Total",
                "Status",
                "Approved By",
                "Posted By",
            ]
        )

        for journal in queryset:
            writer.writerow(
                [
                    journal.entry_number,
                    journal.entry_date,
                    journal.document_date or "",
                    journal.get_voucher_type_display(),
                    journal.get_source_display(),
                    journal.description,
                    journal.total_debit,
                    journal.total_credit,
                    journal.get_status_display(),
                    str(journal.approved_by) if journal.approved_by else "",
                    str(journal.posted_by) if journal.posted_by else "",
                ]
            )

        return response

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        journal = self.get_object()

        if journal.status not in ["DRAFT", "REJECTED"]:
            return Response(
                {"detail": ("Only Draft or Rejected journals can be submitted.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not journal.is_balanced:
            return Response(
                {"detail": "Journal must be balanced before submission."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        journal.status = "PENDING_APPROVAL"
        journal.submitted_at = timezone.now()
        journal.rejected_by = None
        journal.rejected_at = None
        journal.rejection_reason = ""
        journal.save(
            update_fields=[
                "status",
                "submitted_at",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(journal).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        journal = self.get_object()

        if journal.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Only journals pending approval can be approved.")},
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
    def reject(self, request, pk=None):
        journal = self.get_object()

        if journal.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Only journals pending approval can be rejected.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response(
                {"detail": "Rejection reason is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        journal.status = "REJECTED"
        journal.rejected_by = request.user
        journal.rejected_at = timezone.now()
        journal.rejection_reason = reason
        journal.approved_by = None
        journal.approved_at = None
        journal.save(
            update_fields=[
                "status",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(journal).data)

    def _post_journal(self, journal, user):
        if journal.status != "APPROVED":
            raise ValueError("Journal must be approved before posting.")

        if not journal.is_balanced:
            raise ValueError("Journal is not balanced.")

        restricted = [
            line.account
            for line in journal.lines.select_related("account")
            if not line.account.is_active or line.account.lock_from_posting
        ]

        if restricted:
            raise ValueError(
                "Posting is blocked for: " + ", ".join(str(item) for item in restricted)
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
        journal.posted_by = user
        journal.posted_at = timezone.now()
        journal.save(
            update_fields=[
                "status",
                "posted_by",
                "posted_at",
                "updated_at",
            ]
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def post(self, request, pk=None):
        journal = self.get_object()

        try:
            self._post_journal(journal, request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(self.get_serializer(journal).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def duplicate(self, request, pk=None):
        source = self.get_object()

        prefix = timezone.now().strftime("JV-%Y%m")
        count = JournalEntry.objects.filter(entry_number__startswith=prefix).count()

        journal = JournalEntry.objects.create(
            entry_number=f"{prefix}-{count + 1:04d}",
            entry_date=timezone.localdate(),
            document_date=timezone.localdate(),
            branch=source.branch,
            voucher_type=source.voucher_type,
            source="MANUAL",
            reference=source.reference,
            description=f"Copy of {source.entry_number} - {source.description}",
            currency=source.currency,
            exchange_rate=source.exchange_rate,
            approval_workflow=source.approval_workflow,
            approver=source.approver,
            approval_priority=source.approval_priority,
            approval_comments=source.approval_comments,
            created_by=request.user,
            status="DRAFT",
        )

        for line in source.lines.all():
            JournalLine.objects.create(
                journal=journal,
                account=line.account,
                description=line.description,
                cost_center=line.cost_center,
                project=line.project,
                debit=line.debit,
                credit=line.credit,
            )

        return Response(
            self.get_serializer(journal).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, pk=None):
        source = self.get_object()

        if source.status != "POSTED":
            return Response(
                {"detail": "Only Posted journals can be reversed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if source.reversal_entries.filter(status="POSTED").exists():
            return Response(
                {"detail": "This journal already has a posted reversal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prefix = timezone.now().strftime("JV-%Y%m")
        count = JournalEntry.objects.filter(entry_number__startswith=prefix).count()

        reversal_date = request.data.get("reversal_date")
        if reversal_date:
            from datetime import date

            posting_date = date.fromisoformat(str(reversal_date))
        else:
            posting_date = timezone.localdate()

        narration = (
            str(request.data.get("narration") or "").strip()
            or source.reversal_narration
            or f"Reversal of {source.entry_number}"
        )

        reversal = JournalEntry.objects.create(
            entry_number=f"{prefix}-{count + 1:04d}",
            entry_date=posting_date,
            document_date=posting_date,
            branch=source.branch,
            voucher_type="REVERSAL",
            source="SYSTEM",
            reference=source.entry_number,
            description=narration,
            currency=source.currency,
            exchange_rate=source.exchange_rate,
            status="APPROVED",
            approved_by=request.user,
            approved_at=timezone.now(),
            reversed_from=source,
            created_by=request.user,
        )

        for line in source.lines.all():
            JournalLine.objects.create(
                journal=reversal,
                account=line.account,
                description=f"Reversal - {line.description}".strip(" -"),
                cost_center=line.cost_center,
                project=line.project,
                debit=line.credit,
                credit=line.debit,
            )

        try:
            self._post_journal(reversal, request.user)
        except ValueError as exc:
            raise ValueError(str(exc))

        source.status = "REVERSED"
        source.save(update_fields=["status", "updated_at"])

        return Response(
            self.get_serializer(reversal).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def attachments(self, request, pk=None):
        journal = self.get_object()

        files = request.FILES.getlist("files")
        if not files and request.FILES.get("file"):
            files = [request.FILES["file"]]

        if not files:
            return Response(
                {"detail": "Select at least one file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        for file in files:
            attachment = JournalAttachment.objects.create(
                journal=journal,
                file=file,
                original_name=file.name,
                uploaded_by=request.user,
            )
            created.append(attachment)

        return Response(
            JournalAttachmentSerializer(
                created,
                many=True,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"attachments/(?P<attachment_id>[^/.]+)",
    )
    def delete_attachment(self, request, pk=None, attachment_id=None):
        journal = self.get_object()

        if journal.status not in ["DRAFT", "REJECTED"]:
            return Response(
                {"detail": ("Attachments cannot be changed after submission.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attachment = journal.attachments.filter(pk=attachment_id).first()
        if not attachment:
            return Response(
                {"detail": "Attachment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        attachment.file.delete(save=False)
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        ReceivableInvoice.objects.select_related(
            "branch", "customer", "revenue_account", "posted_by", "cancelled_by"
        )
        .prefetch_related("lines", "receipts", "attachments__uploaded_by")
        .order_by("-invoice_date", "-id")
    )
    serializer_class = ReceivableInvoiceSerializer
    filterset_fields = ["branch", "customer", "status", "invoice_date", "due_date"]
    search_fields = [
        "invoice_number",
        "customer__name",
        "customer_po_reference",
        "invoice_narration",
        "notes",
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        requested_status = self.request.query_params.get("status")
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)
        if requested_status == "OVERDUE":
            qs = qs.exclude(
                status__in=["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"]
            ).filter(due_date__lt=timezone.localdate())
        elif requested_status:
            qs = qs.filter(status=requested_status)
        return qs.distinct()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        qs = self.filter_queryset(self.get_queryset())
        open_qs = qs.exclude(status__in=["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"])
        overdue_qs = open_qs.filter(due_date__lt=today)
        next_7 = open_qs.filter(
            due_date__gte=today, due_date__lte=today + timedelta(days=7)
        )
        receipts = ReceivableReceipt.objects.filter(
            receipt_date__gte=month_start, receipt_date__lt=next_month
        )
        branch_id = request.query_params.get("branch")
        if branch_id:
            receipts = receipts.filter(branch_id=branch_id)
        return Response(
            {
                "total_receivables": str(
                    sum((x.balance_due for x in open_qs), Decimal("0"))
                ),
                "open_invoice_count": open_qs.count(),
                "overdue_amount": str(
                    sum((x.balance_due for x in overdue_qs), Decimal("0"))
                ),
                "overdue_invoice_count": overdue_qs.count(),
                "received_this_month": str(
                    receipts.aggregate(value=Sum("amount"))["value"] or Decimal("0")
                ),
                "receipts_this_month_count": receipts.count(),
                "due_next_7_days": str(
                    sum((x.balance_due for x in next_7), Decimal("0"))
                ),
                "due_next_7_days_count": next_7.count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="aging-summary")
    def aging_summary(self, request):
        today = timezone.localdate()
        qs = self.filter_queryset(self.get_queryset()).exclude(
            status__in=["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"]
        )
        keys = ["current", "days_1_30", "days_31_60", "days_61_90", "days_90_plus"]
        buckets = {k: Decimal("0") for k in keys}
        counts = {f"{k}_count": 0 for k in keys}
        customers = {}
        for invoice in qs:
            age = (today - invoice.due_date).days
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
            value = Decimal(invoice.balance_due or 0)
            buckets[key] += value
            counts[f"{key}_count"] += 1
            row = customers.setdefault(
                invoice.customer_id,
                {
                    "customer_id": invoice.customer_id,
                    "customer_name": invoice.customer.name,
                    **{k: Decimal("0") for k in keys},
                    "total": Decimal("0"),
                },
            )
            row[key] += value
            row["total"] += value
        return Response(
            {
                "buckets": {**{k: str(v) for k, v in buckets.items()}, **counts},
                "by_customer": [
                    {**r, **{k: str(r[k]) for k in keys}, "total": str(r["total"])}
                    for r in customers.values()
                ],
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="accounts-receivable.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Invoice No.",
                "Customer",
                "Invoice Date",
                "Due Date",
                "Invoice Amount",
                "Paid",
                "Balance",
                "Status",
                "Reference",
            ]
        )
        for invoice in self.filter_queryset(self.get_queryset()):
            writer.writerow(
                [
                    invoice.invoice_number,
                    invoice.customer.name,
                    invoice.invoice_date,
                    invoice.due_date,
                    invoice.total_amount,
                    invoice.paid_amount,
                    invoice.balance_due,
                    invoice.get_status_display(),
                    invoice.customer_po_reference,
                ]
            )
        return response

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def post(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != "DRAFT":
            return Response(
                {"detail": "Only Draft invoices can be posted."}, status=400
            )
        if not invoice.revenue_account_id:
            return Response(
                {"detail": "Revenue Account is required before posting."}, status=400
            )
        serializer = self.get_serializer(invoice)
        if (
            serializer.get_exceeds_credit_limit(invoice)
            and not invoice.credit_override_approved
        ):
            return Response(
                {
                    "detail": "Customer credit limit is exceeded. Approved override is required."
                },
                status=400,
            )
        ar_account = (
            ChartOfAccount.objects.filter(
                Q(branch=invoice.branch) | Q(branch__isnull=True),
                sub_type="ACCOUNTS_RECEIVABLE",
                is_active=True,
                lock_from_posting=False,
            )
            .order_by("-branch_id", "code")
            .first()
        )
        if not ar_account:
            return Response(
                {
                    "detail": "Accounts Receivable ledger account is not configured for this branch."
                },
                status=400,
            )
        vat_account = None
        if Decimal(invoice.vat_amount or 0) > 0:
            vat_account = (
                ChartOfAccount.objects.filter(
                    Q(branch=invoice.branch) | Q(branch__isnull=True),
                    sub_type="VAT_PAYABLE",
                    is_active=True,
                    lock_from_posting=False,
                )
                .order_by("-branch_id", "code")
                .first()
            )
            if not vat_account:
                return Response(
                    {
                        "detail": "VAT Payable ledger account is not configured for this branch."
                    },
                    status=400,
                )
        revenue = invoice.revenue_account
        if not revenue.is_active or revenue.lock_from_posting:
            return Response(
                {"detail": "Revenue Account is blocked from posting."}, status=400
            )
        ar_account.current_balance = Decimal(ar_account.current_balance or 0) + Decimal(
            invoice.total_amount or 0
        )
        ar_account.save(update_fields=["current_balance", "updated_at"])
        LedgerEntry.objects.create(
            entry_number=f"{invoice.invoice_number}-AR",
            branch=invoice.branch,
            account=ar_account,
            ledger_type=ar_account.account_type,
            transaction_type="RECEIVABLE_INVOICE",
            reference_type="ReceivableInvoice",
            reference_id=str(invoice.id),
            debit_amount=invoice.total_amount,
            credit_amount=0,
            balance=ar_account.current_balance,
            transaction_date=invoice.invoice_date,
            remarks=invoice.invoice_narration or invoice.invoice_number,
        )
        revenue_value = Decimal(invoice.taxable_amount or 0)
        revenue.current_balance = Decimal(revenue.current_balance or 0) + revenue_value
        revenue.save(update_fields=["current_balance", "updated_at"])
        LedgerEntry.objects.create(
            entry_number=f"{invoice.invoice_number}-REV",
            branch=invoice.branch,
            account=revenue,
            ledger_type=revenue.account_type,
            transaction_type="RECEIVABLE_INVOICE",
            reference_type="ReceivableInvoice",
            reference_id=str(invoice.id),
            debit_amount=0,
            credit_amount=revenue_value,
            balance=revenue.current_balance,
            transaction_date=invoice.invoice_date,
            remarks=invoice.invoice_narration or invoice.invoice_number,
        )
        if vat_account:
            vat_value = Decimal(invoice.vat_amount or 0)
            vat_account.current_balance = (
                Decimal(vat_account.current_balance or 0) + vat_value
            )
            vat_account.save(update_fields=["current_balance", "updated_at"])
            LedgerEntry.objects.create(
                entry_number=f"{invoice.invoice_number}-VAT",
                branch=invoice.branch,
                account=vat_account,
                ledger_type=vat_account.account_type,
                transaction_type="RECEIVABLE_INVOICE",
                reference_type="ReceivableInvoice",
                reference_id=str(invoice.id),
                debit_amount=0,
                credit_amount=vat_value,
                balance=vat_account.current_balance,
                transaction_date=invoice.invoice_date,
                remarks=f"VAT - {invoice.invoice_number}",
            )
        invoice.status = "OPEN"
        invoice.posted_at = timezone.now()
        invoice.posted_by = request.user
        invoice.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != "DRAFT":
            return Response(
                {
                    "detail": "Only Draft invoices can be cancelled directly. Posted corrections use Sales Return / accounting reversal."
                },
                status=400,
            )
        invoice.status = "CANCELLED"
        invoice.cancelled_at = timezone.now()
        invoice.cancelled_by = request.user
        invoice.save(
            update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"]
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="send-reminder")
    def send_reminder(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status in ["DRAFT", "PAID", "CANCELLED", "WRITTEN_OFF"]:
            return Response(
                {"detail": "Payment reminder cannot be sent for this invoice."},
                status=400,
            )
        invoice.last_reminder_sent_at = timezone.now()
        invoice.save(update_fields=["last_reminder_sent_at", "updated_at"])
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def attachments(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != "DRAFT":
            return Response(
                {"detail": "Attachments cannot be changed after posting."}, status=400
            )
        files = request.FILES.getlist("files") or (
            [request.FILES["file"]] if request.FILES.get("file") else []
        )
        if not files:
            return Response({"detail": "Select at least one file."}, status=400)
        created = [
            ReceivableInvoiceAttachment.objects.create(
                invoice=invoice, file=f, original_name=f.name, uploaded_by=request.user
            )
            for f in files
        ]
        return Response(
            ReceivableInvoiceAttachmentSerializer(
                created, many=True, context={"request": request}
            ).data,
            status=201,
        )

    @action(detail=False, methods=["get"], url_path="customer-statement")
    def customer_statement(self, request):
        customer_id = request.query_params.get("customer")
        if not customer_id:
            return Response({"detail": "Customer is required."}, status=400)
        today = timezone.localdate()
        period = request.query_params.get("period", "CURRENT_MONTH")
        if period == "LAST_MONTH":
            current = today.replace(day=1)
            date_to = current - timedelta(days=1)
            date_from = date_to.replace(day=1)
        elif period == "CUSTOM":
            date_from = request.query_params.get("date_from")
            date_to = request.query_params.get("date_to")
        else:
            date_from = today.replace(day=1)
            date_to = today
        invoices = (
            self.get_queryset()
            .filter(customer_id=customer_id)
            .exclude(status__in=["DRAFT", "CANCELLED"])
        )
        receipts = ReceivableReceipt.objects.filter(customer_id=customer_id)
        branch_id = request.query_params.get("branch")
        if branch_id:
            invoices = invoices.filter(branch_id=branch_id)
            receipts = receipts.filter(branch_id=branch_id)
        if date_from:
            invoices = invoices.filter(invoice_date__gte=date_from)
            receipts = receipts.filter(receipt_date__gte=date_from)
        if date_to:
            invoices = invoices.filter(invoice_date__lte=date_to)
            receipts = receipts.filter(receipt_date__lte=date_to)
        entries = [
            {
                "date": x.invoice_date,
                "document_no": x.invoice_number,
                "type": "Invoice",
                "description": x.invoice_narration or "Customer invoice",
                "debit": Decimal(x.total_amount or 0),
                "credit": Decimal("0"),
            }
            for x in invoices
        ]
        entries += [
            {
                "date": x.receipt_date,
                "document_no": x.receipt_number,
                "type": "Receipt",
                "description": x.reference or x.get_payment_method_display(),
                "debit": Decimal("0"),
                "credit": Decimal(x.amount or 0),
            }
            for x in receipts
        ]
        entries.sort(key=lambda r: (r["date"], r["document_no"]))
        balance = Decimal("0")
        rows = []
        for row in entries:
            balance += row["debit"] - row["credit"]
            rows.append(
                {
                    **row,
                    "date": str(row["date"]),
                    "debit": str(row["debit"]),
                    "credit": str(row["credit"]),
                    "balance": str(balance),
                }
            )
        return Response({"rows": rows, "closing_balance": str(balance)})


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
        if not receipt.invoice_id:
            return
        invoice = ReceivableInvoice.objects.select_for_update().get(
            pk=receipt.invoice_id
        )
        new_paid = Decimal(invoice.paid_amount or 0) + Decimal(receipt.amount or 0)
        if new_paid > Decimal(invoice.total_amount or 0):
            raise ValueError("Receipt would exceed the invoice total.")
        invoice.paid_amount = new_paid
        invoice.status = (
            "PAID" if new_paid >= invoice.total_amount else "PARTIALLY_PAID"
        )
        invoice.save(update_fields=["paid_amount", "status", "updated_at"])


class FixedAssetViewSet(GenericViewSet):
    queryset = (
        FixedAsset.objects.select_related(
            "branch",
            "supplier",
            "fixed_asset_account",
            "accumulated_depreciation_account",
            "depreciation_expense_account",
            "disposal_gain_loss_account",
            "approver",
        )
        .prefetch_related("attachments")
        .order_by("-id")
    )
    serializer_class = FixedAssetSerializer
    filterset_fields = ["branch", "category", "status", "custodian"]
    search_fields = [
        "asset_tag",
        "asset_name",
        "serial_number",
        "barcode",
        "manufacturer",
        "model",
    ]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset()).exclude(status="DISPOSED")
        total_cost = sum((a.capitalized_cost for a in qs), Decimal("0"))
        accum = qs.aggregate(v=Sum("accumulated_depreciation"))["v"] or Decimal("0")
        due = qs.filter(
            next_service_date__lte=timezone.localdate() + timedelta(days=30),
            next_service_date__gte=timezone.localdate(),
        ).count()
        return Response(
            {
                "total_asset_cost": str(total_cost),
                "accumulated_depreciation": str(accum),
                "net_book_value": str(total_cost - accum),
                "assets_due_service": due,
            }
        )

    @action(detail=True, methods=["post"], url_path="submit-approval")
    def submit_approval(self, request, pk=None):
        asset = self.get_object()
        if asset.status not in ["DRAFT", "REJECTED"]:
            return Response(
                {"detail": "Only Draft or Rejected assets can be submitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset.status = "PENDING_APPROVAL"
        asset.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        asset = self.get_object()
        if asset.status != "PENDING_APPROVAL":
            return Response(
                {"detail": "Only pending assets can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset.status = "APPROVED"
        asset.approved_by = request.user
        asset.approved_at = timezone.now()
        asset.save()
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def capitalize(self, request, pk=None):
        asset = self.get_object()
        if asset.status != "APPROVED":
            return Response(
                {"detail": "Asset must be approved before capitalization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset.status = "ACTIVE"
        asset.capitalized_by = request.user
        asset.capitalized_at = timezone.now()
        asset.save()
        LedgerEntry.objects.create(
            entry_number=f"{asset.asset_tag}-CAP",
            branch=asset.branch,
            account=asset.fixed_asset_account,
            ledger_type=asset.fixed_asset_account.account_type,
            transaction_type="FIXED_ASSET_CAPITALIZATION",
            reference_type="FixedAsset",
            reference_id=str(asset.id),
            debit_amount=asset.capitalized_cost,
            credit_amount=0,
            balance=asset.fixed_asset_account.current_balance,
            transaction_date=asset.capitalization_date,
            remarks=f"Capitalization - {asset.asset_name}",
        )
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def attachments(self, request, pk=None):
        asset = self.get_object()
        if asset.status not in ["DRAFT", "REJECTED"]:
            return Response(
                {"detail": "Attachments cannot be changed after approval."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows = [
            FixedAssetAttachment.objects.create(
                asset=asset, file=f, original_name=f.name, uploaded_by=request.user
            )
            for f in request.FILES.getlist("files")
        ]
        return Response(
            FixedAssetAttachmentSerializer(
                rows, many=True, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class FixedAssetDepreciationViewSet(GenericViewSet):
    queryset = FixedAssetDepreciation.objects.select_related(
        "asset", "branch"
    ).order_by("-period", "asset__asset_tag")
    serializer_class = FixedAssetDepreciationSerializer
    filterset_fields = ["branch", "period", "status", "asset"]

    @action(detail=False, methods=["post"], url_path="post-period")
    @transaction.atomic
    def post_period(self, request):
        period = request.data.get("period")
        if not period:
            return Response(
                {"detail": "period is required in YYYY-MM format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        posted = 0
        for asset in FixedAsset.objects.filter(status="ACTIVE", depreciate_asset=True):
            if (
                asset.depreciation_method == "NO_DEPRECIATION"
                or asset.net_book_value <= asset.residual_value
            ):
                continue
            monthly = (asset.capitalized_cost - asset.residual_value) / Decimal(
                max(1, asset.useful_life_months)
            )
            dep = min(monthly, asset.net_book_value - asset.residual_value)
            row, created = FixedAssetDepreciation.objects.get_or_create(
                asset=asset,
                branch=asset.branch,
                period=period,
                defaults={
                    "opening_nbv": asset.net_book_value,
                    "depreciation_amount": dep,
                    "closing_nbv": asset.net_book_value - dep,
                    "status": "POSTED",
                    "journal_reference": f"DEP-{asset.asset_tag}-{period}",
                },
            )
            if not created:
                continue
            asset.accumulated_depreciation += dep
            if asset.net_book_value <= asset.residual_value:
                asset.status = "FULLY_DEPRECIATED"
            asset.save(
                update_fields=["accumulated_depreciation", "status", "updated_at"]
            )
            posted += 1
        return Response({"posted": posted})


class FixedAssetTransferViewSet(GenericViewSet):
    queryset = FixedAssetTransfer.objects.select_related(
        "asset", "branch", "approved_by"
    )
    serializer_class = FixedAssetTransferSerializer
    filterset_fields = ["branch", "asset", "status"]


class FixedAssetMaintenanceViewSet(GenericViewSet):
    queryset = FixedAssetMaintenance.objects.select_related("asset", "branch")
    serializer_class = FixedAssetMaintenanceSerializer
    filterset_fields = ["branch", "asset", "status", "maintenance_type"]


class FixedAssetDisposalViewSet(GenericViewSet):
    queryset = FixedAssetDisposal.objects.select_related("asset", "branch")
    serializer_class = FixedAssetDisposalSerializer
    filterset_fields = ["branch", "asset", "status", "disposal_method"]


class VatViewSet(GenericViewSet):
    queryset = TaxRate.objects.none()
    serializer_class = TaxRateSerializer

    def _date_filters(self, request):
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        branch_id = _branch_id(request)
        return (
            date_from,
            date_to,
            branch_id,
        )

    def _sales_queryset(
        self,
        request,
    ):
        date_from, date_to, branch_id = self._date_filters(request)

        queryset = ReceivableInvoice.objects.select_related(
            "branch",
            "customer",
        ).exclude(
            status__in=[
                "DRAFT",
                "CANCELLED",
                "WRITTEN_OFF",
            ]
        )

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if date_from:
            queryset = queryset.filter(invoice_date__gte=date_from)

        if date_to:
            queryset = queryset.filter(invoice_date__lte=date_to)

        return queryset

    def _purchase_queryset(
        self,
        request,
    ):
        date_from, date_to, branch_id = self._date_filters(request)

        queryset = PayableBill.objects.select_related(
            "branch",
            "supplier",
        ).exclude(
            status__in=[
                "DRAFT",
                "REJECTED",
                "CANCELLED",
            ]
        )

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if date_from:
            queryset = queryset.filter(bill_date__gte=date_from)

        if date_to:
            queryset = queryset.filter(bill_date__lte=date_to)

        return queryset

    @action(
        detail=False,
        methods=["get"],
    )
    def dashboard(
        self,
        request,
    ):
        sales = self._sales_queryset(request)
        purchases = self._purchase_queryset(request)

        output_vat = sales.aggregate(value=Sum("vat_amount"))["value"] or Decimal("0")

        input_vat = purchases.aggregate(value=Sum("vat_amount"))["value"] or Decimal(
            "0"
        )

        standard_sales = sales.aggregate(value=Sum("taxable_amount"))[
            "value"
        ] or Decimal("0")

        taxable_purchases = purchases.aggregate(value=Sum("taxable_amount"))[
            "value"
        ] or Decimal("0")

        sales_count = sales.count()
        purchase_count = purchases.count()

        return Response(
            {
                "standard_rated_supplies": str(standard_sales),
                "zero_rated_supplies": "0",
                "exempt_supplies": "0",
                "taxable_purchases": str(taxable_purchases),
                "output_vat": str(output_vat),
                "input_vat": str(input_vat),
                "net_vat_payable": str(output_vat - input_vat),
                "tax_exceptions": 0,
                "valid_transactions": (sales_count + purchase_count),
                "warnings_count": 0,
                "errors_count": 0,
                "total_transactions": (sales_count + purchase_count),
                "readiness": [
                    {
                        "label": ("Sales VAT transactions"),
                        "status": "VALID",
                    },
                    {
                        "label": ("Purchase VAT transactions"),
                        "status": "VALID",
                    },
                    {
                        "label": ("VAT ledger reconciliation"),
                        "status": "VALID",
                    },
                ],
                "return_boxes": [
                    {
                        "box_number": "1",
                        "description": ("Standard Rated Supplies"),
                        "taxable_amount": str(standard_sales),
                        "vat_amount": str(output_vat),
                        "adjustment_amount": "0",
                        "final_amount": str(output_vat),
                        "status": "VALID",
                    },
                    {
                        "box_number": "9",
                        "description": ("Recoverable Input Tax"),
                        "taxable_amount": str(taxable_purchases),
                        "vat_amount": str(input_vat),
                        "adjustment_amount": "0",
                        "final_amount": str(input_vat),
                        "status": "VALID",
                    },
                ],
            }
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def transactions(
        self,
        request,
    ):
        rows = []

        for invoice in self._sales_queryset(request):
            rows.append(
                {
                    "id": (f"sale-{invoice.id}"),
                    "transaction_date": (invoice.invoice_date),
                    "document_number": (invoice.invoice_number),
                    "transaction_type": ("OUTPUT"),
                    "party_name": (invoice.customer.name),
                    "party_trn": getattr(
                        invoice.customer,
                        "trn",
                        "",
                    ),
                    "tax_code": (
                        "VAT_STANDARD"
                        if Decimal(invoice.vat_amount or 0) > 0
                        else "NON_VAT"
                    ),
                    "taxable_amount": str(invoice.taxable_amount or 0),
                    "vat_amount": str(invoice.vat_amount or 0),
                    "branch_name": (invoice.branch.branch_name),
                    "validation_status": ("VALID"),
                }
            )

        for bill in self._purchase_queryset(request):
            rows.append(
                {
                    "id": (f"purchase-{bill.id}"),
                    "transaction_date": (bill.bill_date),
                    "document_number": (bill.bill_number),
                    "transaction_type": ("INPUT"),
                    "party_name": (bill.supplier.name),
                    "party_trn": getattr(
                        bill.supplier,
                        "trn",
                        "",
                    ),
                    "tax_code": (
                        "VAT_STANDARD"
                        if Decimal(bill.vat_amount or 0) > 0
                        else "NON_VAT"
                    ),
                    "taxable_amount": str(bill.taxable_amount or 0),
                    "vat_amount": str(bill.vat_amount or 0),
                    "branch_name": (bill.branch.branch_name),
                    "validation_status": ("VALID"),
                }
            )

        rows.sort(
            key=lambda row: str(row["transaction_date"]),
            reverse=True,
        )

        return Response(rows)

    @action(
        detail=False,
        methods=["get"],
    )
    def reconciliation(
        self,
        request,
    ):
        dashboard = self.dashboard(request).data

        settings = VatSettings.objects.first()

        output_ledger = Decimal("0")
        input_ledger = Decimal("0")

        if settings and settings.output_vat_account_id:
            output_ledger = Decimal(settings.output_vat_account.current_balance or 0)

        if settings and settings.input_vat_account_id:
            input_ledger = Decimal(settings.input_vat_account.current_balance or 0)

        return_net = Decimal(dashboard["net_vat_payable"])

        ledger_net = output_ledger - input_ledger

        difference = ledger_net - return_net

        rows = []

        if settings:
            for account, return_amount in [
                (
                    settings.output_vat_account,
                    Decimal(dashboard["output_vat"]),
                ),
                (
                    settings.input_vat_account,
                    Decimal(dashboard["input_vat"]),
                ),
            ]:
                if not account:
                    continue

                closing = Decimal(account.current_balance or 0)

                rows.append(
                    {
                        "account_name": (f"{account.code} — " f"{account.name}"),
                        "opening_balance": "0",
                        "period_debit": "0",
                        "period_credit": "0",
                        "closing_balance": str(closing),
                        "return_amount": str(return_amount),
                        "difference": str(closing - return_amount),
                        "status": (
                            "VALID" if closing == return_amount else "EXCEPTION"
                        ),
                    }
                )

        return Response(
            {
                "output_vat_ledger": str(output_ledger),
                "input_vat_ledger": str(input_ledger),
                "return_net_vat": str(return_net),
                "difference": str(difference),
                "rows": rows,
            }
        )


class VatReturnViewSet(GenericViewSet):
    queryset = (
        VatReturn.objects.select_related(
            "branch_scope",
            "assigned_approver",
            "submitted_by",
            "approved_by",
            "filed_by",
        )
        .prefetch_related("boxes")
        .order_by(
            "-period_to",
            "-id",
        )
    )

    serializer_class = VatReturnSerializer

    filterset_fields = [
        "status",
        "return_type",
        "return_frequency",
        "branch_scope",
        "payment_status",
    ]

    @action(
        detail=False,
        methods=["post"],
    )
    @transaction.atomic
    def prepare(
        self,
        request,
    ):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        sales = ReceivableInvoice.objects.exclude(
            status__in=[
                "DRAFT",
                "CANCELLED",
                "WRITTEN_OFF",
            ]
        ).filter(
            invoice_date__gte=(data["period_from"]),
            invoice_date__lte=(data["period_to"]),
        )

        purchases = PayableBill.objects.exclude(
            status__in=[
                "DRAFT",
                "REJECTED",
                "CANCELLED",
            ]
        ).filter(
            bill_date__gte=(data["period_from"]),
            bill_date__lte=(data["period_to"]),
        )

        branch_scope = data.get("branch_scope")

        if branch_scope:
            sales = sales.filter(branch=branch_scope)
            purchases = purchases.filter(branch=branch_scope)

        output_vat = sales.aggregate(value=Sum("vat_amount"))["value"] or Decimal("0")

        input_vat = purchases.aggregate(value=Sum("vat_amount"))["value"] or Decimal(
            "0"
        )

        prior_credit = Decimal(
            data.get(
                "prior_period_credit",
                0,
            )
            or 0
        )

        vat_return = VatReturn.objects.create(
            **data,
            output_vat=output_vat,
            input_vat=input_vat,
            net_vat_payable=max(
                Decimal("0"),
                output_vat - input_vat - prior_credit,
            ),
            total_transactions=(sales.count() + purchases.count()),
            valid_transactions=(sales.count() + purchases.count()),
            warnings_count=0,
            errors_count=0,
            status="DRAFT",
        )

        sales_taxable = sales.aggregate(value=Sum("taxable_amount"))[
            "value"
        ] or Decimal("0")

        purchase_taxable = purchases.aggregate(value=Sum("taxable_amount"))[
            "value"
        ] or Decimal("0")

        VatReturnBox.objects.create(
            vat_return=vat_return,
            box_number="1",
            description=("Standard Rated Supplies"),
            taxable_amount=sales_taxable,
            vat_amount=output_vat,
            adjustment_amount=0,
            final_amount=output_vat,
            status="VALID",
        )

        VatReturnBox.objects.create(
            vat_return=vat_return,
            box_number="9",
            description=("Recoverable Input Tax"),
            taxable_amount=purchase_taxable,
            vat_amount=input_vat,
            adjustment_amount=0,
            final_amount=input_vat,
            status="VALID",
        )

        return Response(
            self.get_serializer(vat_return).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def validate(
        self,
        request,
        pk=None,
    ):
        vat_return = self.get_object()

        if vat_return.status not in [
            "DRAFT",
            "REJECTED",
        ]:
            return Response(
                {"detail": ("Only Draft or Rejected " "returns can be validated.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if vat_return.errors_count:
            return Response(
                {"detail": ("Resolve VAT return errors " "before validation.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vat_return.status = "VALIDATED"
        vat_return.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(vat_return).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="submit-approval",
    )
    def submit_approval(
        self,
        request,
        pk=None,
    ):
        vat_return = self.get_object()

        if vat_return.status != "VALIDATED":
            return Response(
                {"detail": ("VAT return must be " "validated first.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vat_return.status = "PENDING_APPROVAL"
        vat_return.submitted_by = request.user
        vat_return.submitted_at = timezone.now()
        vat_return.reviewer_notes = str(
            request.data.get("reviewer_notes") or vat_return.reviewer_notes or ""
        )

        vat_return.save(
            update_fields=[
                "status",
                "submitted_by",
                "submitted_at",
                "reviewer_notes",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(vat_return).data)

    @action(
        detail=True,
        methods=["post"],
    )
    def approve(
        self,
        request,
        pk=None,
    ):
        vat_return = self.get_object()

        if vat_return.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("VAT return must be " "pending approval.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vat_return.status = "APPROVED"
        vat_return.approved_by = request.user
        vat_return.approved_at = timezone.now()

        vat_return.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(vat_return).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="mark-filed",
    )
    def mark_filed(
        self,
        request,
        pk=None,
    ):
        vat_return = self.get_object()

        if vat_return.status != "APPROVED":
            return Response(
                {"detail": ("Only Approved VAT returns " "can be filed.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filing_reference = str(request.data.get("filing_reference") or "").strip()

        if not filing_reference:
            return Response(
                {"detail": ("Filing reference is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vat_return.filing_reference = filing_reference
        vat_return.submission_date = timezone.localdate()
        vat_return.filed_by = request.user
        vat_return.payment_status = request.data.get("payment_status") or "NOT_PAID"
        vat_return.payment_reference = str(request.data.get("payment_reference") or "")
        vat_return.payment_account = str(request.data.get("payment_account") or "")

        vat_return.status = "PAID" if vat_return.payment_status == "PAID" else "FILED"

        vat_return.save(
            update_fields=[
                "filing_reference",
                "submission_date",
                "filed_by",
                "payment_status",
                "payment_reference",
                "payment_account",
                "status",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(vat_return).data)


class VatSettingsViewSet(GenericViewSet):
    queryset = VatSettings.objects.select_related(
        "output_vat_account",
        "input_vat_account",
        "vat_payable_account",
    )

    serializer_class = VatSettingsSerializer

    @action(
        detail=False,
        methods=[
            "get",
            "put",
            "patch",
        ],
    )
    def current(
        self,
        request,
    ):
        instance = self.get_queryset().first()

        if request.method == "GET":
            if not instance:
                instance = VatSettings.objects.create()

            return Response(self.get_serializer(instance).data)

        if not instance:
            instance = VatSettings.objects.create()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=(request.method == "PATCH"),
        )

        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(serializer.data)


class TaxRateViewSet(GenericViewSet):
    queryset = TaxRate.objects.select_related("branch")
    serializer_class = TaxRateSerializer


class BudgetViewSet(GenericViewSet):
    queryset = (
        Budget.objects.select_related(
            "branch_scope",
            "budget_owner",
            "primary_approver",
            "submitted_by",
            "approved_by",
            "rejected_by",
            "activated_by",
        )
        .prefetch_related(
            "lines__account",
            "lines__branch",
        )
        .order_by(
            "-fiscal_year",
            "-id",
        )
    )

    serializer_class = BudgetSerializer

    filterset_fields = [
        "status",
        "fiscal_year",
        "budget_type",
        "branch_scope",
        "budget_owner",
    ]

    search_fields = [
        "budget_number",
        "budget_name",
        "description",
        "department_scope",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch = self.request.query_params.get("branch")

        fiscal_year = self.request.query_params.get("fiscal_year")

        if branch not in (
            None,
            "",
            "all",
        ):
            queryset = queryset.filter(
                Q(branch_scope_id=branch) | Q(branch_scope__isnull=True)
            )

        if fiscal_year:
            queryset = queryset.filter(fiscal_year=fiscal_year)

        return queryset.distinct()

    @action(
        detail=False,
        methods=["get"],
    )
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        active = queryset.filter(
            status__in=[
                "APPROVED",
                "ACTIVE",
            ]
        )

        approved_budget = sum(
            (budget.total_budget for budget in active),
            Decimal("0"),
        )

        lines = []

        for budget in active:
            for line in budget.lines.select_related(
                "account",
                "branch",
            ):
                annual = Decimal(line.annual_total or 0)

                ledger_queryset = LedgerEntry.objects.filter(
                    account=line.account,
                    transaction_date__gte=budget.start_date,
                    transaction_date__lte=min(
                        budget.end_date,
                        timezone.localdate(),
                    ),
                )

                if line.branch_id:
                    ledger_queryset = ledger_queryset.filter(branch_id=line.branch_id)
                elif budget.branch_scope_id:
                    ledger_queryset = ledger_queryset.filter(
                        branch_id=budget.branch_scope_id
                    )

                actual = ledger_queryset.aggregate(value=Sum("debit_amount"))[
                    "value"
                ] or Decimal("0")

                if line.account.normal_balance == "CREDIT":
                    actual = ledger_queryset.aggregate(value=Sum("credit_amount"))[
                        "value"
                    ] or Decimal("0")

                committed = Decimal("0")

                used = (
                    ((actual + committed) / annual) * Decimal("100")
                    if annual
                    else Decimal("0")
                )

                available = annual - actual - committed

                variance = annual - actual

                line_status = (
                    "OVER_BUDGET"
                    if used > budget.block_threshold_percent
                    else (
                        "WARNING"
                        if used >= budget.warning_threshold_percent
                        else "WITHIN_BUDGET"
                    )
                )

                lines.append(
                    {
                        "budget_id": budget.id,
                        "budget_name": (budget.budget_name),
                        "account_code": (line.account.code),
                        "account_name": (line.account.name),
                        "department": (line.department),
                        "branch_name": (
                            getattr(
                                line.branch,
                                "branch_name",
                                None,
                            )
                            or getattr(
                                line.branch,
                                "name",
                                None,
                            )
                            or (
                                getattr(
                                    budget.branch_scope,
                                    "branch_name",
                                    None,
                                )
                                if budget.branch_scope
                                else None
                            )
                            or "All Branches"
                        ),
                        "annual_budget": str(annual),
                        "actual_ytd": str(actual),
                        "committed": str(committed),
                        "available": str(available),
                        "variance": str(variance),
                        "used_percent": str(used),
                        "revision_label": (f"Rev {budget.version}"),
                        "status": (line_status),
                    }
                )

        actual_total = sum(
            (Decimal(row["actual_ytd"]) for row in lines),
            Decimal("0"),
        )

        committed_total = sum(
            (Decimal(row["committed"]) for row in lines),
            Decimal("0"),
        )

        departments = {}

        for row in lines:
            key = row["department"] or "Unassigned"

            current = departments.setdefault(
                key,
                {
                    "budget": Decimal("0"),
                    "used": Decimal("0"),
                },
            )

            current["budget"] += Decimal(row["annual_budget"])

            current["used"] += Decimal(row["actual_ytd"]) + Decimal(row["committed"])

        by_department = []

        for name, values in departments.items():
            percentage = (
                (values["used"] / values["budget"]) * Decimal("100")
                if values["budget"]
                else Decimal("0")
            )

            by_department.append(
                {
                    "department": name,
                    "budget": str(values["budget"]),
                    "used": str(values["used"]),
                    "utilization_percent": str(percentage),
                }
            )

        return Response(
            {
                "approved_budget": str(approved_budget),
                "actual_spend_ytd": str(actual_total),
                "committed_spend": str(committed_total),
                "over_budget_lines": sum(
                    1 for row in lines if row["status"] == "OVER_BUDGET"
                ),
                "over_budget_requests": 0,
                "approved_this_month": (
                    queryset.filter(
                        approved_at__year=(timezone.localdate().year),
                        approved_at__month=(timezone.localdate().month),
                    ).count()
                ),
                "lines": lines,
                "by_department": (by_department),
            }
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def variance(self, request):
        summary_data = self.summary(request).data

        analysis = []

        favorable = Decimal("0")
        unfavorable = Decimal("0")

        for row in summary_data["lines"]:
            budget_ytd = Decimal(row["annual_budget"])
            actual_ytd = Decimal(row["actual_ytd"])
            committed = Decimal(row["committed"])

            variance = budget_ytd - actual_ytd

            if variance >= 0:
                favorable += variance
            else:
                unfavorable += abs(variance)

            percentage = (
                (variance / budget_ytd) * Decimal("100") if budget_ytd else Decimal("0")
            )

            analysis.append(
                {
                    "account_name": (row["account_name"]),
                    "department": (row["department"]),
                    "budget_ytd": str(budget_ytd),
                    "actual_ytd": str(actual_ytd),
                    "committed": str(committed),
                    "forecast": str(actual_ytd + committed),
                    "variance": str(variance),
                    "variance_percent": str(percentage),
                    "status": (row["status"]),
                }
            )

        return Response(
            {
                "favorable_variance": str(favorable),
                "unfavorable_variance": str(unfavorable),
                "forecast_at_completion": str(
                    Decimal(summary_data["actual_spend_ytd"])
                    + Decimal(summary_data["committed_spend"])
                ),
                "forecast_variance": str(
                    Decimal(summary_data["approved_budget"])
                    - Decimal(summary_data["actual_spend_ytd"])
                    - Decimal(summary_data["committed_spend"])
                ),
                "analysis": analysis,
                "lines": (summary_data["lines"]),
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="submit-approval",
    )
    def submit_approval(
        self,
        request,
        pk=None,
    ):
        budget = self.get_object()

        if budget.status not in [
            "DRAFT",
            "REJECTED",
        ]:
            return Response(
                {"detail": ("Only Draft or Rejected " "budgets can be submitted.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        budget.status = "PENDING_APPROVAL"
        budget.submitted_by = request.user
        budget.submitted_at = timezone.now()
        budget.rejected_by = None
        budget.rejected_at = None
        budget.rejection_reason = ""

        budget.save(
            update_fields=[
                "status",
                "submitted_by",
                "submitted_at",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(budget).data)

    @action(
        detail=True,
        methods=["post"],
    )
    def approve(
        self,
        request,
        pk=None,
    ):
        budget = self.get_object()

        if budget.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Budget must be pending " "approval.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        budget.status = "APPROVED"
        budget.approved_by = request.user
        budget.approved_at = timezone.now()

        budget.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(budget).data)

    @action(
        detail=True,
        methods=["post"],
    )
    def reject(
        self,
        request,
        pk=None,
    ):
        budget = self.get_object()

        reason = str(request.data.get("reason") or "").strip()

        if budget.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Budget must be pending " "approval.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not reason:
            return Response(
                {"detail": ("Rejection reason is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        budget.status = "REJECTED"
        budget.rejected_by = request.user
        budget.rejected_at = timezone.now()
        budget.rejection_reason = reason

        budget.save(
            update_fields=[
                "status",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(budget).data)

    @action(
        detail=True,
        methods=["post"],
    )
    def activate(
        self,
        request,
        pk=None,
    ):
        budget = self.get_object()

        if budget.status != "APPROVED":
            return Response(
                {"detail": ("Budget must be approved " "before activation.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        budget.status = "ACTIVE"
        budget.activated_by = request.user
        budget.activated_at = timezone.now()

        budget.save(
            update_fields=[
                "status",
                "activated_by",
                "activated_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(budget).data)


class BudgetRevisionViewSet(GenericViewSet):
    queryset = BudgetRevision.objects.select_related(
        "budget",
        "from_account",
        "to_account",
        "approved_by",
    ).order_by(
        "-revision_date",
        "-id",
    )

    serializer_class = BudgetRevisionSerializer

    filterset_fields = [
        "budget",
        "status",
        "revision_type",
    ]

    search_fields = [
        "revision_number",
        "budget__budget_name",
        "reason",
    ]

    @action(
        detail=True,
        methods=["post"],
    )
    def submit(
        self,
        request,
        pk=None,
    ):
        revision = self.get_object()

        if revision.status != "DRAFT":
            return Response(
                {"detail": ("Only Draft revisions " "can be submitted.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        revision.status = "PENDING_APPROVAL"
        revision.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(revision).data)

    @action(
        detail=True,
        methods=["post"],
    )
    @transaction.atomic
    def approve(
        self,
        request,
        pk=None,
    ):
        revision = self.get_object()

        if revision.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Revision must be pending " "approval.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        revision.status = "APPROVED"
        revision.approved_by = request.user
        revision.approved_at = timezone.now()
        revision.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        budget = revision.budget
        budget.version += 1
        budget.save(
            update_fields=[
                "version",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(revision).data)


class AccountingPeriodViewSet(GenericViewSet):
    queryset = AccountingPeriod.objects.select_related("branch")
    serializer_class = AccountingPeriodSerializer


class AccountingDashboardViewSet(GenericViewSet):
    queryset = ChartOfAccount.objects.none()
    serializer_class = ChartOfAccountSerializer


class BankTransactionViewSet(GenericViewSet):
    queryset = BankTransaction.objects.select_related(
        "branch",
        "bank_account",
        "reconciled_by",
    ).order_by(
        "-transaction_date",
        "-id",
    )

    serializer_class = BankTransactionSerializer

    filterset_fields = [
        "branch",
        "bank_account",
        "transaction_type",
        "reconciliation_status",
    ]

    search_fields = [
        "voucher_number",
        "particulars",
        "reference",
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

    @transaction.atomic
    def perform_create(self, serializer):
        transaction = serializer.save()

        account = BankAccount.objects.select_for_update().get(
            pk=transaction.bank_account_id
        )

        account.current_balance = (
            Decimal(account.current_balance or 0)
            + Decimal(transaction.receipt_amount or 0)
            - Decimal(transaction.payment_amount or 0)
        )

        account.save(
            update_fields=[
                "current_balance",
                "updated_at",
            ]
        )

        transaction.running_balance = account.current_balance

        transaction.save(
            update_fields=[
                "running_balance",
                "updated_at",
            ]
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def reconcile(
        self,
        request,
        pk=None,
    ):
        transaction = self.get_object()

        transaction.reconciliation_status = "RECONCILED"
        transaction.reconciled_at = timezone.now()
        transaction.reconciled_by = request.user

        transaction.save(
            update_fields=[
                "reconciliation_status",
                "reconciled_at",
                "reconciled_by",
                "updated_at",
            ]
        )

        account = transaction.bank_account

        account.last_reconciled_date = transaction.transaction_date

        account.save(
            update_fields=[
                "last_reconciled_date",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(transaction).data)

    @action(
        detail=False,
        methods=["get"],
    )
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        response = HttpResponse(content_type="text/csv")

        response["Content-Disposition"] = 'attachment; filename="bank-cashbook.csv"'

        writer = csv.writer(response)

        writer.writerow(
            [
                "Voucher",
                "Date",
                "Account",
                "Type",
                "Particulars",
                "Reference",
                "Receipt",
                "Payment",
                "Running Balance",
                "Reconciliation",
            ]
        )

        for transaction in queryset:
            writer.writerow(
                [
                    transaction.voucher_number,
                    transaction.transaction_date,
                    transaction.bank_account.account_name,
                    transaction.get_transaction_type_display(),
                    transaction.particulars,
                    transaction.reference,
                    transaction.receipt_amount,
                    transaction.payment_amount,
                    transaction.running_balance,
                    transaction.reconciliation_status,
                ]
            )

        return response


class BankFundTransferViewSet(GenericViewSet):
    queryset = BankFundTransfer.objects.select_related(
        "branch",
        "from_account",
        "to_account",
        "journal",
    ).order_by(
        "-transfer_date",
        "-id",
    )

    serializer_class = BankFundTransferSerializer

    filterset_fields = [
        "branch",
        "from_account",
        "to_account",
        "transfer_date",
    ]

    @transaction.atomic
    def perform_create(
        self,
        serializer,
    ):
        transfer = serializer.save(status="POSTED")

        source = BankAccount.objects.select_for_update().get(
            pk=transfer.from_account_id
        )

        destination = BankAccount.objects.select_for_update().get(
            pk=transfer.to_account_id
        )

        if source.current_balance < transfer.amount:
            raise serializers.ValidationError(
                {"amount": ("Insufficient source-account balance.")}
            )

        source.current_balance -= transfer.amount

        source.save(
            update_fields=[
                "current_balance",
                "updated_at",
            ]
        )

        destination.current_balance += transfer.amount

        destination.save(
            update_fields=[
                "current_balance",
                "updated_at",
            ]
        )

        BankTransaction.objects.create(
            branch=transfer.branch,
            bank_account=source,
            voucher_number=(f"{transfer.reference_number}-OUT"),
            transaction_date=(transfer.transfer_date),
            transaction_type="TRANSFER",
            particulars=(f"Transfer to " f"{destination.account_name}"),
            receipt_amount=0,
            payment_amount=transfer.amount,
            running_balance=(source.current_balance),
            reference=(transfer.reference_number),
        )

        BankTransaction.objects.create(
            branch=transfer.branch,
            bank_account=destination,
            voucher_number=(f"{transfer.reference_number}-IN"),
            transaction_date=(transfer.transfer_date),
            transaction_type="TRANSFER",
            particulars=(f"Transfer from " f"{source.account_name}"),
            receipt_amount=transfer.amount,
            payment_amount=0,
            running_balance=(destination.current_balance),
            reference=(transfer.reference_number),
        )


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
    queryset = (
        PayableBill.objects.select_related(
            "branch",
            "supplier",
            "expense_account",
            "approver",
            "approved_by",
            "rejected_by",
            "matched_by",
            "posted_by",
        )
        .prefetch_related("lines", "payments", "attachments__uploaded_by")
        .order_by("-bill_date", "-id")
    )

    serializer_class = PayableBillSerializer
    filterset_fields = [
        "branch",
        "supplier",
        "status",
        "bill_date",
        "due_date",
        "match_status",
        "approval_priority",
    ]

    search_fields = [
        "bill_number",
        "supplier_invoice_number",
        "supplier__name",
        "bill_narration",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if date_from:
            queryset = queryset.filter(bill_date__gte=date_from)

        if date_to:
            queryset = queryset.filter(bill_date__lte=date_to)

        return queryset.distinct()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)

        queryset = self.filter_queryset(self.get_queryset())

        open_queryset = queryset.exclude(
            status__in=[
                "DRAFT",
                "PAID",
                "CANCELLED",
            ]
        )

        total_payables = sum(
            (bill.balance_due for bill in open_queryset),
            Decimal("0"),
        )

        overdue_queryset = open_queryset.filter(due_date__lt=today)

        overdue_amount = sum(
            (bill.balance_due for bill in overdue_queryset),
            Decimal("0"),
        )

        due_next_7 = open_queryset.filter(
            due_date__gte=today,
            due_date__lte=today + timedelta(days=7),
        )

        due_next_7_amount = sum(
            (bill.balance_due for bill in due_next_7),
            Decimal("0"),
        )

        payments = PayablePayment.objects.filter(payment_date__gte=month_start)

        branch_id = request.query_params.get("branch")

        if branch_id:
            payments = payments.filter(branch_id=branch_id)

        paid_this_month = payments.aggregate(value=Sum("amount"))["value"] or Decimal(
            "0"
        )

        return Response(
            {
                "total_payables": str(total_payables),
                "open_bill_count": open_queryset.count(),
                "overdue_amount": str(overdue_amount),
                "overdue_count": overdue_queryset.count(),
                "due_next_7_days": str(due_next_7_amount),
                "due_next_7_days_count": due_next_7.count(),
                "paid_this_month": str(paid_this_month),
                "payments_this_month_count": payments.count(),
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="aging-summary",
    )
    def aging_summary(self, request):
        today = timezone.localdate()

        queryset = self.filter_queryset(self.get_queryset()).exclude(
            status__in=[
                "DRAFT",
                "PAID",
                "CANCELLED",
            ]
        )

        keys = [
            "current",
            "days_1_30",
            "days_31_60",
            "days_61_90",
            "days_90_plus",
        ]

        buckets = {key: Decimal("0") for key in keys}

        counts = {f"{key}_count": 0 for key in keys}

        suppliers = {}

        for bill in queryset:
            age = (today - bill.due_date).days

            if age <= 0:
                key = "current"
            elif age <= 30:
                key = "days_1_30"
            elif age <= 60:
                key = "days_31_60"
            elif age <= 90:
                key = "days_61_90"
            else:
                key = "days_90_plus"

            value = bill.balance_due

            buckets[key] += value
            counts[f"{key}_count"] += 1

            row = suppliers.setdefault(
                bill.supplier_id,
                {
                    "supplier_id": bill.supplier_id,
                    "supplier_name": bill.supplier.name,
                    **{item: Decimal("0") for item in keys},
                    "total": Decimal("0"),
                },
            )

            row[key] += value
            row["total"] += value

        return Response(
            {
                "buckets": {
                    **{key: str(value) for key, value in buckets.items()},
                    **counts,
                },
                "by_supplier": [
                    {
                        **row,
                        **{key: str(row[key]) for key in keys},
                        "total": str(row["total"]),
                    }
                    for row in suppliers.values()
                ],
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="submit-approval",
    )
    def submit_approval(self, request, pk=None):
        bill = self.get_object()

        if bill.status not in [
            "DRAFT",
            "REJECTED",
        ]:
            return Response(
                {"detail": ("Only Draft or Rejected bills " "can be submitted.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not bill.attachments.exists():
            return Response(
                {"detail": ("Supplier invoice attachment is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bill.status = "PENDING_APPROVAL"

        bill.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(bill).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        bill = self.get_object()

        if bill.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Only bills pending approval " "can be approved.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bill.status = "APPROVED"
        bill.approved_by = request.user
        bill.approved_at = timezone.now()

        bill.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(bill).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        bill = self.get_object()

        if bill.status != "PENDING_APPROVAL":
            return Response(
                {"detail": ("Only bills pending approval " "can be rejected.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = str(request.data.get("reason") or "").strip()

        if not reason:
            return Response(
                {"detail": ("Rejection reason is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bill.status = "REJECTED"
        bill.rejected_by = request.user
        bill.rejected_at = timezone.now()
        bill.rejection_reason = reason

        bill.save(
            update_fields=[
                "status",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(bill).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="validate-match",
    )
    def validate_match(self, request, pk=None):
        bill = self.get_object()

        if bill.match_method == "NO_PO":
            bill.match_status = "MATCHED"

        elif bill.match_method == "TWO_WAY":
            bill.match_status = "MATCHED" if bill.purchase_order_id else "VARIANCE"

        else:
            bill.match_status = (
                "MATCHED" if (bill.purchase_order_id and bill.grn_id) else "VARIANCE"
            )

        bill.matched_by = request.user
        bill.matched_at = timezone.now()

        bill.save(
            update_fields=[
                "match_status",
                "matched_by",
                "matched_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(bill).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def post(self, request, pk=None):
        bill = self.get_object()

        if bill.status != "APPROVED":
            return Response(
                {"detail": ("Bill must be approved before posting.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if bill.match_method != "NO_PO" and bill.match_status != "MATCHED":
            return Response(
                {"detail": ("PO / GRN matching must be resolved " "before posting.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not bill.expense_account_id:
            return Response(
                {"detail": ("Expense / Inventory Account is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ap_account = (
            ChartOfAccount.objects.filter(
                Q(branch=bill.branch) | Q(branch__isnull=True),
                sub_type="ACCOUNTS_PAYABLE",
                is_active=True,
                lock_from_posting=False,
            )
            .order_by(
                "-branch_id",
                "code",
            )
            .first()
        )

        if not ap_account:
            return Response(
                {"detail": ("Accounts Payable ledger account " "is not configured.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        input_vat_account = None

        if Decimal(bill.vat_amount or 0) > 0:
            input_vat_account = (
                ChartOfAccount.objects.filter(
                    Q(branch=bill.branch) | Q(branch__isnull=True),
                    sub_type__in=[
                        "VAT_INPUT",
                        "VAT_INPUT_RECOVERABLE",
                    ],
                    is_active=True,
                    lock_from_posting=False,
                )
                .order_by(
                    "-branch_id",
                    "code",
                )
                .first()
            )

            if not input_vat_account:
                return Response(
                    {"detail": ("Input VAT ledger account " "is not configured.")},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        LedgerEntry.objects.create(
            entry_number=f"{bill.bill_number}-EXP",
            branch=bill.branch,
            account=bill.expense_account,
            ledger_type=bill.expense_account.account_type,
            transaction_type="PAYABLE_BILL",
            reference_type="PayableBill",
            reference_id=str(bill.id),
            debit_amount=bill.taxable_amount,
            credit_amount=0,
            balance=bill.expense_account.current_balance,
            transaction_date=bill.bill_date,
            remarks=(bill.bill_narration or bill.bill_number),
        )

        if input_vat_account:
            LedgerEntry.objects.create(
                entry_number=f"{bill.bill_number}-VAT",
                branch=bill.branch,
                account=input_vat_account,
                ledger_type=input_vat_account.account_type,
                transaction_type="PAYABLE_BILL",
                reference_type="PayableBill",
                reference_id=str(bill.id),
                debit_amount=bill.vat_amount,
                credit_amount=0,
                balance=input_vat_account.current_balance,
                transaction_date=bill.bill_date,
                remarks=f"Input VAT - {bill.bill_number}",
            )

        LedgerEntry.objects.create(
            entry_number=f"{bill.bill_number}-AP",
            branch=bill.branch,
            account=ap_account,
            ledger_type=ap_account.account_type,
            transaction_type="PAYABLE_BILL",
            reference_type="PayableBill",
            reference_id=str(bill.id),
            debit_amount=0,
            credit_amount=bill.total_amount,
            balance=ap_account.current_balance,
            transaction_date=bill.bill_date,
            remarks=(bill.bill_narration or bill.bill_number),
        )

        bill.status = "POSTED"
        bill.posted_by = request.user
        bill.posted_at = timezone.now()

        bill.save(
            update_fields=[
                "status",
                "posted_by",
                "posted_at",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(bill).data)

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[
            MultiPartParser,
            FormParser,
        ],
    )
    def attachments(self, request, pk=None):
        bill = self.get_object()

        if bill.status not in [
            "DRAFT",
            "REJECTED",
        ]:
            return Response(
                {"detail": ("Attachments cannot be changed " "after submission.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        files = request.FILES.getlist("files")

        if not files:
            return Response(
                {"detail": ("Select at least one file.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []

        for file in files:
            created.append(
                PayableBillAttachment.objects.create(
                    bill=bill,
                    file=file,
                    original_name=file.name,
                    uploaded_by=request.user,
                )
            )

        return Response(
            PayableBillAttachmentSerializer(
                created,
                many=True,
                context={
                    "request": request,
                },
            ).data,
            status=status.HTTP_201_CREATED,
        )


class PayablePaymentViewSet(GenericViewSet):
    queryset = PayablePayment.objects.select_related(
        "branch",
        "bill",
        "supplier",
    ).order_by(
        "-payment_date",
        "-id",
    )

    serializer_class = PayablePaymentSerializer

    filterset_fields = [
        "branch",
        "bill",
        "supplier",
        "payment_date",
        "payment_method",
    ]

    search_fields = [
        "payment_number",
        "bill__bill_number",
        "supplier__name",
        "reference",
    ]

    @transaction.atomic
    def perform_create(self, serializer):
        payment = serializer.save()

        bill = PayableBill.objects.select_for_update().get(pk=payment.bill_id)

        bill.paid_amount = Decimal(bill.paid_amount or 0) + Decimal(payment.amount or 0)

        bill.status = (
            "PAID" if bill.paid_amount >= bill.total_amount else "PARTIALLY_PAID"
        )

        bill.save(
            update_fields=[
                "paid_amount",
                "status",
                "updated_at",
            ]
        )


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


def _financial_report_ledger_queryset(request):
    """
    Shared ledger queryset for all financial reports.
    Supports branch filtering.
    """
    queryset = LedgerEntry.objects.select_related(
        "account",
        "branch",
    )

    branch_id = request.query_params.get("branch")

    if branch_id:
        queryset = queryset.filter(branch_id=branch_id)

    return queryset


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def trial_balance(request):
    """
    Trial Balance as of a selected report date.

    URL:
    /api/finance/reporting/reports/trial-balance/
    """

    report_date = request.query_params.get("report_date") or timezone.localdate()

    display = request.query_params.get(
        "display",
        "BALANCES",
    )

    queryset = (
        _financial_report_ledger_queryset(request)
        .filter(transaction_date__lte=report_date)
        .order_by(
            "account__code",
            "transaction_date",
            "id",
        )
    )

    grouped = {}

    for entry in queryset:
        key = (
            entry.account_id,
            entry.branch_id,
        )

        row = grouped.setdefault(
            key,
            {
                "code": entry.account.code,
                "account_name": entry.account.name,
                "account_group": (
                    getattr(
                        entry.account,
                        "account_type",
                        "",
                    )
                ),
                "branch_name": (
                    getattr(
                        entry.branch,
                        "branch_name",
                        None,
                    )
                    or getattr(
                        entry.branch,
                        "name",
                        None,
                    )
                    or "All"
                ),
                "opening_debit": Decimal("0"),
                "opening_credit": Decimal("0"),
                "period_debit": Decimal("0"),
                "period_credit": Decimal("0"),
                "closing_debit": Decimal("0"),
                "closing_credit": Decimal("0"),
            },
        )

        row["period_debit"] += Decimal(entry.debit_amount or 0)

        row["period_credit"] += Decimal(entry.credit_amount or 0)

    rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for row in grouped.values():
        balance = row["period_debit"] - row["period_credit"]

        if balance >= 0:
            row["closing_debit"] = balance
            total_debit += balance
        else:
            row["closing_credit"] = abs(balance)
            total_credit += abs(balance)

        if display == "BALANCES" and balance == 0:
            continue

        rows.append(
            {
                key: (
                    str(value)
                    if isinstance(
                        value,
                        Decimal,
                    )
                    else value
                )
                for key, value in row.items()
            }
        )

    difference = total_debit - total_credit

    return Response(
        {
            "report_date": str(report_date),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "difference": str(difference),
            "accounts_reported": len(rows),
            "rows": rows,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def income_statement(request):
    """
    Profit & Loss / Income Statement.

    URL:
    /api/finance/reporting/reports/income-statement/
    """

    date_from = request.query_params.get("date_from")

    date_to = request.query_params.get("date_to") or timezone.localdate()

    queryset = _financial_report_ledger_queryset(request)

    if date_from:
        queryset = queryset.filter(transaction_date__gte=date_from)

    queryset = queryset.filter(transaction_date__lte=date_to)

    revenue = Decimal("0")
    cost_of_sales = Decimal("0")
    operating_expenses = Decimal("0")
    other_income = Decimal("0")
    other_expenses = Decimal("0")

    account_rows = {}

    for entry in queryset:
        account = entry.account

        account_type = str(
            getattr(
                account,
                "account_type",
                "",
            )
            or ""
        ).upper()

        sub_type = str(
            getattr(
                account,
                "sub_type",
                "",
            )
            or ""
        ).upper()

        debit = Decimal(entry.debit_amount or 0)

        credit = Decimal(entry.credit_amount or 0)

        if account_type in [
            "INCOME",
            "REVENUE",
        ]:
            amount = credit - debit

            if sub_type in [
                "OTHER_INCOME",
                "NON_OPERATING_INCOME",
            ]:
                other_income += amount
            else:
                revenue += amount

        elif account_type == "EXPENSE":
            amount = debit - credit

            if sub_type in [
                "COST_OF_SALES",
                "COGS",
                "COST_OF_GOODS_SOLD",
            ]:
                cost_of_sales += amount

            elif sub_type in [
                "OTHER_EXPENSE",
                "NON_OPERATING_EXPENSE",
            ]:
                other_expenses += amount

            else:
                operating_expenses += amount

        else:
            continue

        row = account_rows.setdefault(
            account.id,
            {
                "account_code": account.code,
                "account_name": account.name,
                "account_type": account_type,
                "sub_type": sub_type,
                "amount": Decimal("0"),
            },
        )

        if account_type in [
            "INCOME",
            "REVENUE",
        ]:
            row["amount"] += credit - debit
        else:
            row["amount"] += debit - credit

    gross_profit = revenue - cost_of_sales

    operating_profit = gross_profit - operating_expenses

    net_profit = operating_profit + other_income - other_expenses

    rows = []

    rows.append(
        {
            "label": "Revenue",
            "is_group": True,
        }
    )

    for row in account_rows.values():
        if row["account_type"] in ["INCOME", "REVENUE"] and row["sub_type"] not in [
            "OTHER_INCOME",
            "NON_OPERATING_INCOME",
        ]:
            rows.append(
                {
                    "label": (f'{row["account_code"]} — ' f'{row["account_name"]}'),
                    "actual": str(row["amount"]),
                    "budget": "0",
                }
            )

    rows.append(
        {
            "label": "Total Revenue",
            "actual": str(revenue),
            "budget": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Cost of Sales",
            "is_group": True,
        }
    )

    for row in account_rows.values():
        if row["sub_type"] in [
            "COST_OF_SALES",
            "COGS",
            "COST_OF_GOODS_SOLD",
        ]:
            rows.append(
                {
                    "label": (f'{row["account_code"]} — ' f'{row["account_name"]}'),
                    "actual": str(row["amount"]),
                    "budget": "0",
                }
            )

    rows.append(
        {
            "label": "Total Cost of Sales",
            "actual": str(cost_of_sales),
            "budget": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Gross Profit",
            "actual": str(gross_profit),
            "budget": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Operating Expenses",
            "is_group": True,
        }
    )

    for row in account_rows.values():
        if row["account_type"] == "EXPENSE" and row["sub_type"] not in [
            "COST_OF_SALES",
            "COGS",
            "COST_OF_GOODS_SOLD",
            "OTHER_EXPENSE",
            "NON_OPERATING_EXPENSE",
        ]:
            rows.append(
                {
                    "label": (f'{row["account_code"]} — ' f'{row["account_name"]}'),
                    "actual": str(row["amount"]),
                    "budget": "0",
                }
            )

    rows.append(
        {
            "label": "Operating Expenses",
            "actual": str(operating_expenses),
            "budget": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Net Profit",
            "actual": str(net_profit),
            "budget": "0",
            "is_grand_total": True,
        }
    )

    return Response(
        {
            "date_from": date_from,
            "date_to": str(date_to),
            "revenue": str(revenue),
            "cost_of_sales": str(cost_of_sales),
            "gross_profit": str(gross_profit),
            "operating_expenses": str(operating_expenses),
            "operating_profit": str(operating_profit),
            "other_income": str(other_income),
            "other_expenses": str(other_expenses),
            "net_profit": str(net_profit),
            "rows": rows,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def balance_sheet(request):
    """
    Balance Sheet as of a selected date.

    URL:
    /api/finance/reporting/reports/balance-sheet/
    """

    report_date = request.query_params.get("report_date") or timezone.localdate()

    queryset = _financial_report_ledger_queryset(request).filter(
        transaction_date__lte=report_date
    )

    assets = Decimal("0")
    liabilities = Decimal("0")
    equity = Decimal("0")

    account_rows = {}

    for entry in queryset:
        account = entry.account

        account_type = str(
            getattr(
                account,
                "account_type",
                "",
            )
            or ""
        ).upper()

        debit = Decimal(entry.debit_amount or 0)

        credit = Decimal(entry.credit_amount or 0)

        if account_type == "ASSET":
            amount = debit - credit
            assets += amount

        elif account_type == "LIABILITY":
            amount = credit - debit
            liabilities += amount

        elif account_type == "EQUITY":
            amount = credit - debit
            equity += amount

        else:
            continue

        row = account_rows.setdefault(
            account.id,
            {
                "code": account.code,
                "name": account.name,
                "account_type": account_type,
                "amount": Decimal("0"),
            },
        )

        row["amount"] += amount

    liability_equity = liabilities + equity

    difference = assets - liability_equity

    rows = [
        {
            "label": "Assets",
            "is_group": True,
        }
    ]

    for row in account_rows.values():
        if row["account_type"] == "ASSET":
            rows.append(
                {
                    "label": (f'{row["code"]} — ' f'{row["name"]}'),
                    "current": str(row["amount"]),
                    "comparison": "0",
                }
            )

    rows.append(
        {
            "label": "Total Assets",
            "current": str(assets),
            "comparison": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Liabilities",
            "is_group": True,
        }
    )

    for row in account_rows.values():
        if row["account_type"] == "LIABILITY":
            rows.append(
                {
                    "label": (f'{row["code"]} — ' f'{row["name"]}'),
                    "current": str(row["amount"]),
                    "comparison": "0",
                }
            )

    rows.append(
        {
            "label": "Total Liabilities",
            "current": str(liabilities),
            "comparison": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": "Equity",
            "is_group": True,
        }
    )

    for row in account_rows.values():
        if row["account_type"] == "EQUITY":
            rows.append(
                {
                    "label": (f'{row["code"]} — ' f'{row["name"]}'),
                    "current": str(row["amount"]),
                    "comparison": "0",
                }
            )

    rows.append(
        {
            "label": "Total Equity",
            "current": str(equity),
            "comparison": "0",
            "is_total": True,
        }
    )

    rows.append(
        {
            "label": ("Total Liabilities & Equity"),
            "current": str(liability_equity),
            "comparison": "0",
            "is_grand_total": True,
        }
    )

    return Response(
        {
            "report_date": str(report_date),
            "total_assets": str(assets),
            "total_liabilities": str(liabilities),
            "total_equity": str(equity),
            "difference": str(difference),
            "rows": rows,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cash_flow(request):
    """
    Cash Flow Statement.

    URL:
    /api/finance/reporting/reports/cash-flow/

    Uses account sub_type where available.

    For best accuracy, assign cash flow categories to
    your ChartOfAccount records:
    OPERATING, INVESTING, FINANCING.
    """

    date_from = request.query_params.get("date_from")

    date_to = request.query_params.get("date_to") or timezone.localdate()

    queryset = _financial_report_ledger_queryset(request)

    if date_from:
        queryset = queryset.filter(transaction_date__gte=date_from)

    queryset = queryset.filter(transaction_date__lte=date_to)

    operating = Decimal("0")
    investing = Decimal("0")
    financing = Decimal("0")

    rows_by_category = {
        "OPERATING": Decimal("0"),
        "INVESTING": Decimal("0"),
        "FINANCING": Decimal("0"),
    }

    for entry in queryset:
        sub_type = str(
            getattr(
                entry.account,
                "sub_type",
                "",
            )
            or ""
        ).upper()

        debit = Decimal(entry.debit_amount or 0)

        credit = Decimal(entry.credit_amount or 0)

        movement = debit - credit

        if sub_type in [
            "OPERATING",
            "OPERATING_CASH_FLOW",
        ]:
            operating += movement
            rows_by_category["OPERATING"] += movement

        elif sub_type in [
            "INVESTING",
            "INVESTING_CASH_FLOW",
            "FIXED_ASSET",
        ]:
            investing += movement
            rows_by_category["INVESTING"] += movement

        elif sub_type in [
            "FINANCING",
            "FINANCING_CASH_FLOW",
            "LOAN",
            "SHARE_CAPITAL",
        ]:
            financing += movement
            rows_by_category["FINANCING"] += movement

    net_change = operating + investing + financing

    return Response(
        {
            "date_from": date_from,
            "date_to": str(date_to),
            "operating_cash_flow": str(operating),
            "investing_cash_flow": str(investing),
            "financing_cash_flow": str(financing),
            "net_change_in_cash": str(net_change),
            "rows": [
                {
                    "label": ("Net Cash from " "Operating Activities"),
                    "current": str(operating),
                    "comparison": "0",
                    "is_total": True,
                },
                {
                    "label": ("Net Cash from " "Investing Activities"),
                    "current": str(investing),
                    "comparison": "0",
                    "is_total": True,
                },
                {
                    "label": ("Net Cash from " "Financing Activities"),
                    "current": str(financing),
                    "comparison": "0",
                    "is_total": True,
                },
                {
                    "label": ("Net Change in Cash"),
                    "current": str(net_change),
                    "comparison": "0",
                    "is_grand_total": True,
                },
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def changes_in_equity(request):
    """
    Statement of Changes in Equity.

    URL:
    /api/finance/reporting/reports/changes-in-equity/
    """

    date_from = request.query_params.get("date_from")

    date_to = request.query_params.get("date_to") or timezone.localdate()

    queryset = _financial_report_ledger_queryset(request)

    if date_from:
        queryset = queryset.filter(transaction_date__gte=date_from)

    queryset = queryset.filter(transaction_date__lte=date_to)

    share_capital = Decimal("0")
    retained_earnings = Decimal("0")
    current_year_profit = Decimal("0")

    for entry in queryset:
        account_type = str(
            getattr(
                entry.account,
                "account_type",
                "",
            )
            or ""
        ).upper()

        sub_type = str(
            getattr(
                entry.account,
                "sub_type",
                "",
            )
            or ""
        ).upper()

        debit = Decimal(entry.debit_amount or 0)

        credit = Decimal(entry.credit_amount or 0)

        if account_type == "EQUITY":
            amount = credit - debit

            if sub_type in [
                "SHARE_CAPITAL",
                "CAPITAL",
                "OWNER_CAPITAL",
            ]:
                share_capital += amount

            elif sub_type in [
                "CURRENT_YEAR_EARNINGS",
                "CURRENT_YEAR_PROFIT",
            ]:
                current_year_profit += amount

            else:
                retained_earnings += amount

    total_equity = share_capital + retained_earnings + current_year_profit

    return Response(
        {
            "date_from": date_from,
            "date_to": str(date_to),
            "rows": [
                {
                    "description": ("Closing Balance"),
                    "share_capital": str(share_capital),
                    "retained_earnings": str(retained_earnings),
                    "current_year_profit": str(current_year_profit),
                    "total_equity": str(total_equity),
                }
            ],
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def period_close(request):
    period_id = request.query_params.get("period")

    periods = AccountingPeriod.objects.all().order_by("-start_date")

    period = periods.filter(pk=period_id).first() if period_id else periods.first()

    if not period:
        return Response(
            {
                "period": None,
                "checklist_completion": 0,
                "blocking_issues": 0,
                "reconciliations_complete": 0,
                "reconciliations_total": 0,
                "target_close_date": None,
                "checklist": [],
                "reconciliations": [],
                "adjustments": [],
                "locks": [],
                "history": [],
            }
        )

    related_tasks = getattr(
        period,
        "tasks",
        None,
    )

    tasks = (
        list(related_tasks.all())
        if related_tasks
        and hasattr(
            related_tasks,
            "all",
        )
        else []
    )

    completed = sum(
        1
        for task in tasks
        if getattr(
            task,
            "completed",
            False,
        )
    )

    total = len(tasks)

    checklist = [
        {
            "id": task.id,
            "title": getattr(
                task,
                "title",
                "",
            ),
            "module": getattr(
                task,
                "module",
                "",
            ),
            "owner_name": str(
                getattr(
                    task,
                    "owner",
                    "",
                )
                or ""
            ),
            "due_date": getattr(
                task,
                "due_date",
                None,
            ),
            "completed": bool(
                getattr(
                    task,
                    "completed",
                    False,
                )
            ),
            "status": (
                "COMPLETE"
                if getattr(
                    task,
                    "completed",
                    False,
                )
                else "PENDING"
            ),
        }
        for task in tasks
    ]

    return Response(
        {
            "period": {
                "id": period.id,
                "name": getattr(
                    period,
                    "name",
                    str(period),
                ),
                "start_date": period.start_date,
                "end_date": period.end_date,
                "status": getattr(
                    period,
                    "status",
                    "OPEN",
                ),
            },
            "checklist_completion": (completed / total * 100 if total else 0),
            "blocking_issues": 0,
            "reconciliations_complete": 0,
            "reconciliations_total": 0,
            "target_close_date": getattr(
                period,
                "target_close_date",
                None,
            ),
            "checklist": checklist,
            "reconciliation_summary": {
                "completed": 0,
                "pending": 0,
                "difference": "0",
                "accounts_checked": 0,
            },
            "reconciliations": [],
            "adjustment_summary": {
                "draft": 0,
                "posted": 0,
                "accruals": "0",
                "prepayments": "0",
            },
            "adjustments": [],
            "locks": [],
            "history": [],
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def period_task_toggle(
    request,
    period_id,
    task_id,
):
    period = get_object_or_404(
        AccountingPeriod,
        pk=period_id,
    )

    related = getattr(
        period,
        "tasks",
        None,
    )

    if not related or not hasattr(
        related,
        "filter",
    ):
        return Response(
            {"detail": ("Period checklist task model " "is not configured.")},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task = get_object_or_404(
        related.all(),
        pk=task_id,
    )

    task.completed = bool(request.data.get("completed"))

    update_fields = ["completed"]

    if hasattr(
        task,
        "updated_at",
    ):
        update_fields.append("updated_at")

    task.save(update_fields=update_fields)

    return Response(
        {
            "success": True,
            "completed": task.completed,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def period_action(
    request,
    period_id,
    action,
):
    period = get_object_or_404(
        AccountingPeriod,
        pk=period_id,
    )

    action = str(action).lower()

    if action in [
        "close",
        "lock",
    ]:
        if hasattr(
            period,
            "status",
        ):
            period.status = "CLOSED"

        if hasattr(
            period,
            "is_locked",
        ):
            period.is_locked = True

        fields = []

        if hasattr(
            period,
            "status",
        ):
            fields.append("status")

        if hasattr(
            period,
            "is_locked",
        ):
            fields.append("is_locked")

        if hasattr(
            period,
            "updated_at",
        ):
            fields.append("updated_at")

        if fields:
            period.save(update_fields=fields)

        return Response(
            {
                "success": True,
                "status": "CLOSED",
            }
        )

    if action == "reopen":
        reason = str(request.data.get("reason") or "").strip()

        if not reason:
            return Response(
                {"detail": ("Reason is required to " "reopen a closed period.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if hasattr(
            period,
            "status",
        ):
            period.status = "OPEN"

        if hasattr(
            period,
            "is_locked",
        ):
            period.is_locked = False

        fields = []

        if hasattr(
            period,
            "status",
        ):
            fields.append("status")

        if hasattr(
            period,
            "is_locked",
        ):
            fields.append("is_locked")

        if hasattr(
            period,
            "updated_at",
        ):
            fields.append("updated_at")

        if fields:
            period.save(update_fields=fields)

        return Response(
            {
                "success": True,
                "status": "OPEN",
                "reason": reason,
            }
        )

    return Response(
        {"detail": ("Unsupported period action.")},
        status=status.HTTP_400_BAD_REQUEST,
    )
