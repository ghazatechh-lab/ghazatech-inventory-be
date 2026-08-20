from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    order_count = serializers.IntegerField(
        read_only=True,
        default=0,
    )

    last_order_date = serializers.DateField(
        read_only=True,
        allow_null=True,
    )

    balance_due = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
        default=0,
    )

    status = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = "__all__"

        read_only_fields = [
            "id",
            "customer_code",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
            "deleted_by",
        ]

    def to_internal_value(self, data):
        """
        Normalize legacy/lowercase customer choice values
        and clean common text fields.
        """
        mutable = data.copy() if hasattr(data, "copy") else dict(data)

        customer_type = mutable.get("customer_type")

        category = mutable.get("category")

        if isinstance(
            customer_type,
            str,
        ):
            normalized_type = customer_type.strip().upper()

            # Older frontend versions submitted
            # category values as customer_type.
            if normalized_type in {
                "RETAIL",
                "WHOLESALE",
                "CORPORATE",
                "LEAD",
            }:
                mutable["category"] = normalized_type

                mutable["customer_type"] = "BUSINESS"

            else:
                mutable["customer_type"] = normalized_type

        if isinstance(
            category,
            str,
        ):
            mutable["category"] = category.strip().upper()

        # Normalize common customer identity fields.
        for field in [
            "customer_name",
            "contact_person",
            "email",
            "phone",
            "mobile",
            "trn",
            "trn_number",
        ]:
            value = mutable.get(field)

            if isinstance(
                value,
                str,
            ):
                mutable[field] = value.strip()

        return super().to_internal_value(mutable)

    def get_status(self, obj):
        if not obj.is_active:
            return "INACTIVE"

        balance = (
            getattr(
                obj,
                "balance_due",
                0,
            )
            or 0
        )

        return "OUTSTANDING" if balance > 0 else "ACTIVE"

    def validate(self, attrs):
        branch = attrs.get(
            "branch",
            getattr(
                self.instance,
                "branch",
                None,
            ),
        )

        if branch is None:
            raise serializers.ValidationError(
                {"branch": ("Branch is required " "for every customer.")}
            )

        customer_type = attrs.get(
            "customer_type",
            getattr(
                self.instance,
                "customer_type",
                "BUSINESS",
            ),
        )

        customer_name = str(
            attrs.get(
                "customer_name",
                getattr(
                    self.instance,
                    "customer_name",
                    "",
                ),
            )
            or ""
        ).strip()

        if customer_type == "BUSINESS" and not customer_name:
            raise serializers.ValidationError(
                {"customer_name": ("Company name is required.")}
            )

        email = str(
            attrs.get(
                "email",
                getattr(
                    self.instance,
                    "email",
                    "",
                ),
            )
            or ""
        ).strip()

        phone = str(
            attrs.get(
                "phone",
                getattr(
                    self.instance,
                    "phone",
                    "",
                ),
            )
            or ""
        ).strip()

        mobile = str(
            attrs.get(
                "mobile",
                getattr(
                    self.instance,
                    "mobile",
                    "",
                ),
            )
            or ""
        ).strip()

        trn = str(
            attrs.get(
                "trn",
                getattr(
                    self.instance,
                    "trn",
                    "",
                ),
            )
            or ""
        ).strip()

        trn_number = str(
            attrs.get(
                "trn_number",
                getattr(
                    self.instance,
                    "trn_number",
                    "",
                ),
            )
            or ""
        ).strip()

        effective_trn = trn_number or trn

        # Only check customers inside the same branch.
        duplicate_queryset = Customer.objects.filter(
            branch=branch,
            is_deleted=False,
        )

        # While editing, exclude the current record.
        if self.instance:
            duplicate_queryset = duplicate_queryset.exclude(pk=self.instance.pk)

        errors = {}

        # -------------------------------------------------
        # Customer / company name
        # -------------------------------------------------
        if customer_name:
            duplicate_name = duplicate_queryset.filter(
                customer_name__iexact=(customer_name)
            ).first()

            if duplicate_name:
                errors["customer_name"] = (
                    "A customer with this name "
                    "already exists in the "
                    "selected branch."
                )

        # -------------------------------------------------
        # Email
        # -------------------------------------------------
        if email:
            duplicate_email = duplicate_queryset.filter(email__iexact=email).first()

            if duplicate_email:
                errors["email"] = (
                    "A customer with this email "
                    "already exists in the "
                    "selected branch."
                )

        # -------------------------------------------------
        # Phone
        # -------------------------------------------------
        if phone:
            duplicate_phone = duplicate_queryset.filter(phone=phone).first()

            if duplicate_phone:
                errors["phone"] = (
                    "A customer with this phone "
                    "number already exists in "
                    "the selected branch."
                )

        # -------------------------------------------------
        # Mobile
        # -------------------------------------------------
        if mobile:
            duplicate_mobile = duplicate_queryset.filter(mobile=mobile).first()

            if duplicate_mobile:
                errors["mobile"] = (
                    "A customer with this mobile "
                    "number already exists in "
                    "the selected branch."
                )

        # -------------------------------------------------
        # TRN
        # -------------------------------------------------
        if effective_trn:
            duplicate_trn = duplicate_queryset.filter(
                trn_number__iexact=(effective_trn)
            ).first()

            if not duplicate_trn:
                duplicate_trn = duplicate_queryset.filter(
                    trn__iexact=(effective_trn)
                ).first()

            if duplicate_trn:
                errors["trn_number"] = (
                    "A customer with this TRN "
                    "already exists in the "
                    "selected branch."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        if not validated_data.get("customer_code"):
            branch = validated_data["branch"]

            last_customer = (
                Customer.objects.filter(branch=branch).order_by("-id").first()
            )

            next_number = 1 if not last_customer else last_customer.id + 1

            branch_code = (
                getattr(
                    branch,
                    "branch_code",
                    "BR",
                )
                or "BR"
            )

            validated_data["customer_code"] = (
                f"{branch_code}" f"-CUS-" f"{next_number:05d}"
            )

        if validated_data.get("trn") and not validated_data.get("trn_number"):
            validated_data["trn_number"] = validated_data["trn"]

        if validated_data.get("billing_address") and not validated_data.get("address"):
            validated_data["address"] = validated_data["billing_address"]

        return super().create(validated_data)
