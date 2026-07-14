from rest_framework.viewsets import ModelViewSet
from .models import *
from .serializers import *


class Generic(ModelViewSet):
    pass


class ExpenseViewSet(Generic):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    filterset_fields = ["branch", "category", "expense_date"]


class ExpenseCategoryViewSet(Generic):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer


class CashRegisterViewSet(Generic):
    queryset = CashRegister.objects.all()
    serializer_class = CashRegisterSerializer


class BankAccountViewSet(Generic):
    queryset = BankAccount.objects.all()
    serializer_class = BankAccountSerializer


class LedgerViewSet(Generic):
    queryset = LedgerEntry.objects.all()
    serializer_class = LedgerEntrySerializer
    filterset_fields = [
        "branch",
        "ledger_type",
        "customer",
        "supplier",
        "transaction_type",
    ]
