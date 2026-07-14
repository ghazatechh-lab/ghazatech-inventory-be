from rest_framework import serializers
from .models import *


def ser(m):
    return type(
        m.__name__ + "Serializer",
        (serializers.ModelSerializer,),
        {"Meta": type("Meta", (), {"model": m, "fields": "__all__"})},
    )


ExpenseCategorySerializer = ser(ExpenseCategory)
ExpenseSerializer = ser(Expense)
CashRegisterSerializer = ser(CashRegister)
BankAccountSerializer = ser(BankAccount)
LedgerEntrySerializer = ser(LedgerEntry)
