from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BranchAwareModel, SoftDeleteModel, TimeStampedModel
from django.db.models import F, Q


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
    TAX_TREATMENT_CHOICES = [
        ("VAT", "VAT (5%)"),
        ("ZERO_VAT", "Zero VAT (0%)"),
        ("NON_VAT", "Non-VAT"),
    ]

    product_name = models.CharField(max_length=250)
    sku = models.CharField(max_length=80)
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
    tax_treatment = models.CharField(
        max_length=20,
        choices=TAX_TREATMENT_CHOICES,
        default="VAT",
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "sku"],
                condition=Q(branch__isnull=False),
                name="unique_product_sku_per_branch",
            ),
            models.UniqueConstraint(
                fields=["sku"],
                condition=Q(branch__isnull=True),
                name="unique_unassigned_product_sku",
            ),
        ]
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["branch", "sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["product_name"]),
            models.Index(fields=["branch", "is_active"]),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.rack_id and self.branch_id and self.rack.branch_id != self.branch_id:
            raise ValidationError(
                {"rack": ("Selected rack does not belong to the selected branch.")}
            )

        if self.tax_treatment == "VAT":
            self.vat_rate = Decimal("5.00")
        else:
            self.vat_rate = Decimal("0.00")
            self.vat_inclusive = False

    def save(self, *args, **kwargs):
        if self.tax_treatment == "VAT":
            self.vat_rate = Decimal("5.00")
        else:
            self.vat_rate = Decimal("0.00")
            self.vat_inclusive = False

        super().save(*args, **kwargs)

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
    warehouse = models.CharField(max_length=120, blank=True, default="")

    # A single physical quantity and a single reserved quantity are maintained.
    current_stock = models.PositiveIntegerField(default=0)
    reserved_stock = models.PositiveIntegerField(default=0)
    damaged_stock = models.PositiveIntegerField(default=0)

    reorder_level = models.PositiveIntegerField(default=0)
    last_stock_update = models.DateTimeField(auto_now=True)

    # VAT-aware inventory valuation. Recoverable VAT is excluded from carrying
    # value; non-recoverable VAT is capitalized into inventory cost.
    average_unit_cost_excluding_vat = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    recoverable_vat_per_unit = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    capitalized_vat_per_unit = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    average_unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    last_purchase_cost_excluding_vat = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    last_purchase_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    last_tax_treatment = models.CharField(max_length=20, default="NON_VAT")
    last_vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    valuation_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["product__product_name", "branch__branch_code", "warehouse"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "branch", "warehouse"],
                condition=Q(variant__isnull=True),
                name="unique_base_stock_per_branch_warehouse",
            ),
            models.UniqueConstraint(
                fields=["variant", "branch", "warehouse"],
                condition=Q(variant__isnull=False),
                name="unique_variant_stock_per_branch_warehouse",
            ),
            models.CheckConstraint(
                condition=Q(current_stock__gte=0),
                name="product_stock_current_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_stock__gte=0),
                name="product_stock_reserved_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_stock__lte=F("current_stock")),
                name="reserved_stock_not_above_current_stock",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "branch", "warehouse"]),
            models.Index(fields=["variant", "branch", "warehouse"]),
            models.Index(fields=["branch", "current_stock"]),
        ]

    @property
    def total_quantity(self):
        return int(self.current_stock or 0)

    @property
    def total_available_quantity(self):
        return max(0, int(self.current_stock or 0) - int(self.reserved_stock or 0))

    @property
    def available_stock(self):
        return self.total_available_quantity

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError(
                {
                    "variant": "The selected variant does not belong to the selected product."
                }
            )
        if self.reserved_stock > self.current_stock:
            raise ValidationError(
                {"reserved_stock": "Reserved quantity cannot exceed current stock."}
            )

    @property
    def inventory_value_excluding_vat(self):
        return Decimal(self.total_quantity) * Decimal(
            self.average_unit_cost_excluding_vat or 0
        )

    @property
    def recoverable_vat_value(self):
        return Decimal(self.total_quantity) * Decimal(
            self.recoverable_vat_per_unit or 0
        )

    @property
    def capitalized_vat_value(self):
        return Decimal(self.total_quantity) * Decimal(
            self.capitalized_vat_per_unit or 0
        )

    @property
    def total_inventory_value(self):
        return Decimal(self.total_quantity) * Decimal(self.average_unit_cost or 0)

    def __str__(self):
        item = str(self.variant) if self.variant_id else self.product.product_name
        warehouse = self.warehouse or "Main Warehouse"
        return f"{item} @ {self.branch} / {warehouse}"


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
    warehouse = models.CharField(max_length=120, blank=True, default="")
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
    quantity_before = models.IntegerField(default=0)
    quantity_after = models.IntegerField(default=0)
    unit_cost_excluding_vat = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    vat_treatment = models.CharField(max_length=30, default="OUT_OF_SCOPE")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recoverable_vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    non_recoverable_vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    capitalized_unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    net_value_change = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gross_value_change = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    running_stock_value = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    source_document_type = models.CharField(max_length=80, blank=True)
    source_document_number = models.CharField(max_length=100, blank=True)
    tax_invoice_number = models.CharField(max_length=100, blank=True)
    tax_invoice_date = models.DateField(null=True, blank=True)
    is_vat_relevant = models.BooleanField(default=False)
    valuation_method = models.CharField(max_length=20, default="WEIGHTED_AVERAGE")

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
    adjustment_reason = models.CharField(max_length=40, default="OTHER")
    quantity_difference = models.IntegerField(default=0)
    unit_cost_excluding_vat = models.DecimalField(
        max_digits=14, decimal_places=4, default=0
    )
    vat_treatment = models.CharField(max_length=30, default="OUT_OF_SCOPE")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recoverable_vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    non_recoverable_vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    capitalized_adjustment_value = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    value_before = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    value_after = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    accounting_reference = models.CharField(max_length=100, blank=True)
    approval_notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_adjustments",
    )
    rejection_reason = models.TextField(blank=True)

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
