from django.db import models


class BranchDatabaseProfile(models.Model):
    MODE_MASTER = "MASTER"
    MODE_VAT = "VAT"
    MODE_NON_VAT = "NON_VAT"
    MODE_CHOICES = [
        (MODE_MASTER, "Combined / Master"),
        (MODE_VAT, "VAT"),
        (MODE_NON_VAT, "Non-VAT"),
    ]

    branch = models.OneToOneField(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="database_profile",
    )
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, unique=True)
    database_alias = models.CharField(max_length=40, unique=True)
    is_master_inventory = models.BooleanField(default=False)
    show_combined_reports = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch_id"]

    def __str__(self):
        return f"{self.branch} - {self.mode} ({self.database_alias})"


class MasterInventorySyncLog(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    source_branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="master_inventory_sync_logs",
    )
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="master_inventory_sync_logs",
    )
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="master_inventory_sync_logs",
    )
    master_branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="master_inventory_received_sync_logs",
    )
    source_database = models.CharField(max_length=40)
    source_document_type = models.CharField(max_length=80, blank=True)
    source_document_id = models.CharField(max_length=80, blank=True)
    source_document_number = models.CharField(max_length=120, blank=True)
    movement_type = models.CharField(max_length=40)
    quantity = models.IntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_branch", "status"]),
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["source_document_type", "source_document_id"]),
        ]
