from rest_framework.routers import DefaultRouter
from .views import *

r = DefaultRouter()
r.register("expenses", ExpenseViewSet)
r.register("expense-categories", ExpenseCategoryViewSet)
r.register("cash-register", CashRegisterViewSet)
r.register("bank-accounts", BankAccountViewSet)
r.register("ledger", LedgerViewSet)
urlpatterns = r.urls
