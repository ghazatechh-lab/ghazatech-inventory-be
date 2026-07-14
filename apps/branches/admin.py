from django.contrib import admin
from .models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("branch_code", "branch_name", "city", "emirate", "is_active")
    search_fields = ("branch_name", "branch_code")
