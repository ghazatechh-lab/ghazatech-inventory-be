from django.db import models
from django.core.validators import MinValueValidator
from apps.common.models import TimeStampedModel, BranchAwareModel, SoftDeleteModel


class Brand(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Product(TimeStampedModel, SoftDeleteModel):
    product_name = models.CharField(max_length=250)
    sku = models.CharField(max_length=80, unique=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    compatible_models = models.TextField(blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.SET_NULL
    )
    description = models.TextField(blank=True)
    product_image = models.ImageField(upload_to="products/", null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minimum_selling_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    warranty_period_days = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    rack_location = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["product_name"]),
        ]

    def __str__(self):
        return f"{self.sku} - {self.product_name}"


class ProductStock(TimeStampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stocks"
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, related_name="product_stocks"
    )
    current_stock = models.IntegerField(default=0)
    reserved_stock = models.IntegerField(default=0)
    damaged_stock = models.IntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    last_stock_update = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "branch")

    @property
    def available_stock(self):
        return self.current_stock - self.reserved_stock


class StockMovement(TimeStampedModel):
    MOVES = [
        ("OPENING", "Opening Stock"),
        ("PURCHASE", "Purchase Received"),
        ("SALE", "Sale"),
        ("CUSTOMER_RETURN", "Customer Return"),
        ("SUPPLIER_RETURN", "Supplier Return"),
        ("TRANSFER_OUT", "Stock Transfer Out"),
        ("TRANSFER_IN", "Stock Transfer In"),
        ("ADJUSTMENT", "Manual Adjustment"),
        ("DAMAGED", "Damaged Stock"),
        ("INTERNAL", "Internal Use"),
    ]
    movement_number = models.CharField(max_length=50, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    movement_type = models.CharField(max_length=30, choices=MOVES)
    quantity = models.IntegerField()
    previous_stock = models.IntegerField()
    new_stock = models.IntegerField()
    reference_type = models.CharField(max_length=80, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    remarks = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )


class StockAdjustment(TimeStampedModel, BranchAwareModel):
    TYPES = [("ADD", "Add"), ("DEDUCT", "Deduct")]
    STATUS = [("DRAFT", "Draft"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")]
    adjustment_number = models.CharField(max_length=50, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    adjustment_type = models.CharField(max_length=10, choices=TYPES)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=120)
    remarks = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_adjustments",
    )
    status = models.CharField(max_length=20, choices=STATUS, default="DRAFT")
