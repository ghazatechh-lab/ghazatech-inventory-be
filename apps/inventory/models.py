from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BranchAwareModel, SoftDeleteModel, TimeStampedModel


class Brand(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Rack(TimeStampedModel):
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="racks",
    )
    rack_code = models.CharField(max_length=50)
    rack_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch", "rack_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "rack_code"],
                name="unique_rack_code_per_branch",
            )
        ]
        indexes = [
            models.Index(fields=["branch", "is_active"]),
            models.Index(fields=["rack_code"]),
        ]

    def __str__(self):
        return f"{self.rack_code} - {self.branch}"


class Product(TimeStampedModel, SoftDeleteModel):
    CONDITION_CHOICES = [
        ("NEW", "New"),
        ("USED", "Used"),
        ("REFURBISHED", "Refurbished"),
    ]
    UNIT_CHOICES = [
        ("PCS", "Pcs"),
        ("SET", "Set"),
        ("BOX", "Box"),
        ("PACK", "Pack"),
        ("PAIR", "Pair"),
    ]

    product_name = models.CharField(max_length=250)
    sku = models.CharField(max_length=80, unique=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    rack = models.ForeignKey(
        Rack,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    has_variants = models.BooleanField(default=False)
    compatible_models = models.TextField(blank=True)
    condition = models.CharField(
        max_length=20, choices=CONDITION_CHOICES, default="NEW"
    )
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="PCS")
    vat_inclusive = models.BooleanField(default=True)
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        validators=[MinValueValidator(0)],
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    description = models.TextField(blank=True)
    product_image = models.ImageField(upload_to="products/", null=True, blank=True)
    warranty_period_days = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["product_name"]),
            models.Index(fields=["branch", "is_active"]),
        ]

    def __str__(self):
        return f"{self.sku} - {self.product_name}"


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    attributes = models.JSONField(default=dict, blank=True)
    available_qty = models.PositiveIntegerField(default=0)
    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    retail_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    wholesale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    minimum_selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    is_base = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product", "id"]
        indexes = [models.Index(fields=["product", "is_active"])]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_base=True),
                name="one_base_variant_per_product",
            )
        ]

    def __str__(self):
        if self.is_base:
            return f"{self.product.product_name} - Base stock"
        label = ", ".join(f"{key}: {value}" for key, value in self.attributes.items())
        return f"{self.product.product_name} - {label or 'Variant'}"


class ProductStock(TimeStampedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stocks",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="branch_stocks",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="product_stocks",
    )
    current_stock = models.IntegerField(default=0)
    reserved_stock = models.IntegerField(default=0)
    damaged_stock = models.IntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    last_stock_update = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "product__product_name",
            "branch__branch_code",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "branch"],
                condition=models.Q(variant__isnull=True),
                name="unique_base_product_stock_per_branch",
            ),
            models.UniqueConstraint(
                fields=["variant", "branch"],
                condition=models.Q(variant__isnull=False),
                name="unique_variant_stock_per_branch",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "branch"]),
            models.Index(fields=["variant", "branch"]),
            models.Index(fields=["branch", "current_stock"]),
        ]

    @property
    def available_stock(self):
        return self.current_stock - self.reserved_stock - self.damaged_stock

    def __str__(self):
        item = str(self.variant) if self.variant_id else self.product.product_name
        return f"{item} @ {self.branch}"


class StockMovement(TimeStampedModel):
    MOVES = [
        ("OPENING", "Opening Stock"),
        ("PURCHASE", "Purchase"),
        ("SALE", "Sale"),
        ("CUSTOMER_RETURN", "Customer Return"),
        ("SUPPLIER_RETURN", "Supplier Return"),
        ("TRANSFER_OUT", "Transfer Out"),
        ("TRANSFER_IN", "Transfer In"),
        ("ADJUSTMENT", "Adjustment"),
        ("DAMAGED", "Damaged Stock"),
        ("INTERNAL", "Internal Use"),
    ]

    movement_number = models.CharField(
        max_length=50,
        unique=True,
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    movement_type = models.CharField(
        max_length=30,
        choices=MOVES,
    )
    quantity = models.IntegerField(
        help_text=(
            "Signed quantity. Positive increases stock and " "negative decreases stock."
        )
    )
    previous_stock = models.IntegerField()
    new_stock = models.IntegerField()
    reference_type = models.CharField(
        max_length=80,
        blank=True,
    )
    reference_id = models.CharField(
        max_length=80,
        blank=True,
    )
    remarks = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["variant", "created_at"]),
            models.Index(fields=["movement_type", "created_at"]),
        ]

    def __str__(self):
        return self.movement_number


class StockAdjustment(TimeStampedModel, BranchAwareModel):
    TYPES = [
        ("ADD", "Increase"),
        ("DEDUCT", "Decrease"),
    ]
    STATUS = [
        ("DRAFT", "Draft"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    adjustment_number = models.CharField(
        max_length=50,
        unique=True,
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_adjustments",
    )
    adjustment_type = models.CharField(
        max_length=10,
        choices=TYPES,
    )
    quantity = models.PositiveIntegerField()
    current_quantity = models.IntegerField(default=0)
    actual_quantity_counted = models.IntegerField(
        default=0, validators=[MinValueValidator(0)]
    )
    reason = models.CharField(max_length=120)
    remarks = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_adjustments",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="DRAFT",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    @property
    def signed_quantity(self):
        if self.adjustment_type == "DEDUCT":
            return -self.quantity
        return self.quantity

    def __str__(self):
        return self.adjustment_number
