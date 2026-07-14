from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Role


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("email", "username", "full_name", "role", "branch", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Ghaza",
            {
                "fields": (
                    "full_name",
                    "phone_number",
                    "profile_image",
                    "employee",
                    "role",
                    "branch",
                )
            },
        ),
    )


admin.site.register(Role)
