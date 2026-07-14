from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.models import TimeStampedModel


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


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
        Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
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
