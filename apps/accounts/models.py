from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.common.models import TimeStampedModel


class Role(models.Model):
    """
    Role is now an organisational/job-title grouping only.

    Permissions are assigned directly to User.
    `permissions` remains temporarily for backward database compatibility,
    but it is no longer used by permission checks or exposed for editing.
    It can be removed in a later cleanup migration after production data
    has been verified.
    """

    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    # Legacy field. Do not use for authorization.
    permissions = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser, TimeStampedModel):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)

    profile_image = models.ImageField(
        upload_to="profiles/",
        null=True,
        blank=True,
    )

    employee = models.OneToOneField(
        "hrms.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="user",
    )

    role = models.ForeignKey(
        Role,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    # NEW SOURCE OF TRUTH FOR AUTHORIZATION.
    permissions = models.JSONField(
        default=list,
        blank=True,
        help_text=("Operation-level permissions assigned directly to this user."),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email

    @property
    def permission_codes(self):
        """
        Effective permissions are USER permissions only.

        Role permissions are intentionally ignored.
        Admin/superuser remains unrestricted.
        """
        if self.is_superuser or (
            self.role and str(self.role.code or "").upper() == "ADMIN"
        ):
            return ["*"]

        return sorted(
            {
                str(code).strip()
                for code in (self.permissions or [])
                if str(code).strip()
            }
        )

    def has_operation_permission(self, permission_code):
        if "*" in self.permission_codes:
            return True

        permission_code = str(permission_code or "").strip()

        if permission_code in self.permission_codes:
            return True

        parts = permission_code.split(".")

        if parts and f"{parts[0]}.*" in self.permission_codes:
            return True

        if len(parts) > 1 and f"{parts[0]}.{parts[1]}.*" in self.permission_codes:
            return True

        return False
