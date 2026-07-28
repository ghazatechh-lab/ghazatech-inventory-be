from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.models import TimeStampedModel


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def has_permission(self, permission_code):
        return permission_code in (self.permissions or [])


class User(AbstractUser, TimeStampedModel):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    profile_image = models.ImageField(upload_to="profiles/", null=True, blank=True)
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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email

    @property
    def permission_codes(self):
        if self.is_superuser or (self.role and self.role.code == "ADMIN"):
            return ["*"]
        return list(self.role.permissions or []) if self.role else []

    def has_operation_permission(self, permission_code):
        if self.is_superuser or (self.role and self.role.code == "ADMIN"):
            return True
        return permission_code in self.permission_codes
