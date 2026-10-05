from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied

from apps.branches.models import Branch
from apps.common.branch_access import (
    can_switch_branches,
    can_view_all_branches,
    get_user_branch_id,
)


VAT = "VAT"
NON_VAT = "NON_VAT"
BOTH = "BOTH"

# Operational mapping requested for the new flow.
# Keep this in code so the rollout does not depend on a risky Branch schema
# change. It can later be moved to Branch.sales_mode once the migration is
# fully stabilized.
BRANCH_SALES_MODES = {
    "BR01": VAT,
    "BR02": NON_VAT,
    "BR03": BOTH,
}

SALE_MODE_CHOICES = (
    (VAT, "VAT Sale"),
    (NON_VAT, "Non-VAT Sale"),
)


def normalize_branch_code(branch) -> str:
    return str(getattr(branch, "branch_code", "") or "").strip().upper()


def branch_sales_mode(branch) -> str:
    """Return VAT, NON_VAT or BOTH for an operational branch."""
    code = normalize_branch_code(branch)
    return BRANCH_SALES_MODES.get(code, BOTH)


def allowed_sale_modes(branch) -> list[str]:
    mode = branch_sales_mode(branch)
    if mode == VAT:
        return [VAT]
    if mode == NON_VAT:
        return [NON_VAT]
    return [VAT, NON_VAT]


def normalize_sale_mode(value) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "VAT": VAT,
        "VAT_SALE": VAT,
        "STANDARD_VAT": VAT,
        "NON_VAT": NON_VAT,
        "NONVAT": NON_VAT,
        "NON_VAT_SALE": NON_VAT,
        "OUT_OF_SCOPE": NON_VAT,
    }
    return aliases.get(text, text)


def validate_sale_mode(branch, sale_mode, *, required=True) -> str:
    sale_mode = normalize_sale_mode(sale_mode)
    allowed = allowed_sale_modes(branch)

    if not sale_mode:
        if len(allowed) == 1:
            return allowed[0]
        if required:
            raise ValidationError(
                {"sale_mode": "Select VAT Sale or Non-VAT Sale for this branch."}
            )
        return ""

    if sale_mode not in allowed:
        label = "VAT" if allowed == [VAT] else "Non-VAT"
        raise ValidationError(
            {
                "sale_mode": (
                    f"{getattr(branch, 'branch_name', 'This branch')} "
                    f"only allows {label} sales."
                )
            }
        )
    return sale_mode


def user_can_access_branch(user, branch) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if can_view_all_branches(user):
        return True

    assigned = get_user_branch_id(user)
    if assigned and int(assigned) == int(branch.pk):
        return True

    # branches.switch is intentionally not enough by itself to expose every
    # branch. A switch-capable user still needs a permitted branch assignment
    # unless they also have branches.view_all/admin access.
    return False


def ensure_branch_access(user, branch):
    if not user_can_access_branch(user, branch):
        raise PermissionDenied("You do not have permission to access this branch.")
    return branch


def resolve_branch(value):
    if isinstance(value, Branch):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    branch = None
    if text.isdigit():
        branch = Branch.objects.filter(pk=int(text), is_active=True).first()

    if branch is None:
        branch = Branch.objects.filter(
            branch_code__iexact=text,
            is_active=True,
        ).first()
    return branch


def get_requested_branch(request):
    raw = (
        request.headers.get("X-Branch-ID")
        or request.query_params.get("branch")
    )

    if not raw and request.method.upper() in {"POST", "PUT", "PATCH"}:
        try:
            raw = request.data.get("branch")
        except (AttributeError, TypeError):
            raw = None

    if str(raw or "").lower() == "all":
        return None

    branch = resolve_branch(raw)
    if branch:
        return ensure_branch_access(request.user, branch)

    assigned = get_user_branch_id(request.user)
    if assigned:
        branch = Branch.objects.filter(pk=assigned, is_active=True).first()
        if branch:
            return ensure_branch_access(request.user, branch)

    if can_view_all_branches(request.user):
        return None

    raise PermissionDenied("You do not have permission to access this branch.")


def request_sale_mode(request, branch, *, required=True):
    value = None
    try:
        value = request.data.get("sale_mode") or request.data.get("sale_type")
    except (AttributeError, TypeError):
        pass
    return validate_sale_mode(branch, value, required=required)


def apply_sale_mode_to_request(request, branch):
    """Normalize branch + sale_mode before DRF builds the serializer.

    Branch 1/2 are automatically locked to their only permitted mode.
    Branch 3 requires the user to explicitly choose VAT or Non-VAT.
    """
    mode = request_sale_mode(request, branch, required=True)

    try:
        data = request.data
        old_mutable = getattr(data, "_mutable", None)
        if old_mutable is not None:
            data._mutable = True
        data["branch"] = branch.pk
        data["sale_mode"] = mode
        if old_mutable is not None:
            data._mutable = old_mutable
    except Exception:
        # Validation has still happened; serializers can receive sale_mode
        # explicitly from perform_create where required.
        pass

    return mode


def sale_vat_percentage(sale_mode, standard_rate="5.00"):
    """Transaction-level VAT gate.

    Product VAT settings can refine VAT/zero-rated behavior only when the
    transaction itself is a VAT sale. A Non-VAT transaction always returns 0.
    """
    from decimal import Decimal

    mode = normalize_sale_mode(sale_mode)
    return Decimal(str(standard_rate)) if mode == VAT else Decimal("0.00")


class BranchAccessQuerysetMixin:
    """DRF queryset isolation using branch permissions, never DB aliases."""

    branch_field = "branch"

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        branch = get_requested_branch(request)

        if branch is not None:
            return queryset.filter(**{f"{self.branch_field}_id": branch.pk})

        if can_view_all_branches(request.user):
            return queryset

        # get_requested_branch would already have raised for ordinary users.
        return queryset.none()


class SalesBranchGuardMixin(BranchAccessQuerysetMixin):
    """Apply branch and VAT/Non-VAT rules to sales endpoints."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        if request.method.upper() not in {"POST", "PUT", "PATCH"}:
            return

        model = getattr(getattr(self, "queryset", None), "model", None)
        if model is None:
            return

        field_names = {field.name for field in model._meta.get_fields()}
        if "branch" not in field_names:
            return

        branch = get_requested_branch(request)
        if branch is None:
            raise ValidationError({"branch": "A specific branch is required."})

        if "sale_mode" in field_names:
            apply_sale_mode_to_request(request, branch)
