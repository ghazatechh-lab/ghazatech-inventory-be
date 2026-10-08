from __future__ import annotations

from rest_framework import serializers

from apps.branches.models import Branch
from apps.branch_data.context import set_active_branch_id
from apps.branch_data.services import database_alias_for_branch
from apps.branch_data.physical import (
    COMBINED_BRANCH_CODE,
    PHYSICAL_BRANCH_CODES,
    is_physical_branch,
    request_active_branch,
)


def _canonical_branch(value):
    if value is None:
        return None

    manager = Branch.objects.using("default").filter(is_active=True)
    code = str(getattr(value, "branch_code", "") or "").strip().upper()
    if code:
        return manager.filter(branch_code__iexact=code).first()

    raw = getattr(value, "pk", value)
    text = str(raw or "").strip()
    if text.isdigit():
        return manager.filter(pk=int(text)).first()
    if text:
        return manager.filter(branch_code__iexact=text).first()
    return None


def _request_value(request, key):
    try:
        value = request.data.get(key)
        if value not in (None, ""):
            return value
    except (AttributeError, TypeError):
        pass
    value = request.query_params.get(key)
    return value if value not in (None, "") else None


def requested_purchase_target(request):
    """Return the canonical BR01/BR02 target for a purchase operation.

    Physical BR01/BR02 screens are locked to their active branch. BR03 is
    virtual and must explicitly provide a physical branch in ``branch`` or
    ``target_branch``.  ``target_branch`` accepts BR01/BR02 and VAT/NON_VAT.
    """
    active = request_active_branch(request)

    if is_physical_branch(active):
        return _canonical_branch(active)

    raw = _request_value(request, "branch") or _request_value(request, "target_branch")
    text = str(raw or "").strip().upper().replace("-", "_")
    aliases = {
        "VAT": "BR01",
        "NON_VAT": "BR02",
        "NONVAT": "BR02",
        "BR01": "BR01",
        "BR02": "BR02",
    }
    code = aliases.get(text)

    if not code and text.isdigit():
        candidate = _canonical_branch(text)
        code = str(getattr(candidate, "branch_code", "") or "").upper()

    if code not in PHYSICAL_BRANCH_CODES:
        return None

    return Branch.objects.using("default").filter(
        branch_code__iexact=code,
        is_active=True,
    ).first()



def branch_from_source_value(value):
    text = str(value or "").strip().upper().replace("-", "_")
    if ":" in text:
        text = text.split(":", 1)[0]
    code = {
        "VAT": "BR01",
        "BR01": "BR01",
        "BRANCH_1": "BR01",
        "NON_VAT": "BR02",
        "NONVAT": "BR02",
        "BR02": "BR02",
        "BRANCH_2": "BR02",
    }.get(text)
    if not code:
        return None
    return Branch.objects.using("default").filter(
        branch_code__iexact=code, is_active=True
    ).first()

def require_purchase_target(request):
    branch = requested_purchase_target(request)
    if branch is None:
        raise serializers.ValidationError(
            {
                "branch": (
                    "Select Branch 1 or Branch 2. Branch 3 is a combined "
                    "interface and cannot own purchase data."
                )
            }
        )
    return branch


class PurchasePhysicalBranchSerializerMixin:
    """Reject BR03 ownership at the serializer boundary as a final safeguard."""

    def validate_branch(self, value):
        branch = _canonical_branch(value)
        if not is_physical_branch(branch):
            raise serializers.ValidationError(
                "Select Branch 1 or Branch 2. Branch 3 cannot own purchase data."
            )

        # Return the branch row from the same physical database that will own
        # the purchase record. Branch IDs are mirrored across the databases,
        # but using a default-DB model instance for a VAT/NON_VAT write can
        # trigger cross-database relation validation in Django.
        alias = database_alias_for_branch(branch.pk)
        physical_branch = (
            Branch.objects.using(alias)
            .filter(branch_code__iexact=branch.branch_code, is_active=True)
            .first()
        )
        if physical_branch is None:
            raise serializers.ValidationError(
                f"{branch.branch_code} is not available in the physical branch database."
            )
        return physical_branch


class PurchaseBranchGuardMixin:
    """Resolve purchase requests to a real physical database before DRF work.

    This is intentionally applied to purchases, suppliers, and shipments.
    BR03 remains the active UI branch for combined reads, but any explicit
    physical branch used by form-option GETs or any POST/PUT/PATCH write switches
    ORM routing to BR01/BR02 before related-field validation occurs.
    """

    purchase_write_methods = {"POST", "PUT", "PATCH"}

    @staticmethod
    def _write_request_data_branch(request, branch):
        try:
            data = request.data
            old_mutable = getattr(data, "_mutable", None)
            if old_mutable is not None:
                data._mutable = True
            data["branch"] = branch.pk
            if old_mutable is not None:
                data._mutable = old_mutable
        except Exception:
            pass

    def initial(self, request, *args, **kwargs):
        method = request.method.upper()

        if method in self.purchase_write_methods:
            active = request_active_branch(request)
            target = requested_purchase_target(request)

            # Existing BR03 detail/workflow actions can derive their physical
            # source from the composite resource key instead of asking the user
            # to select the branch again. New records have no resource key and
            # still require an explicit BR01/BR02 target.
            if target is None:
                lookup_name = getattr(self, "lookup_url_kwarg", None) or getattr(self, "lookup_field", "pk")
                raw_lookup = self.kwargs.get(lookup_name) or self.kwargs.get("pk")
                target = branch_from_source_value(raw_lookup)
                if target is None:
                    target = branch_from_source_value(request.query_params.get("source_branch"))

            if target is None:
                target = require_purchase_target(request)

            # BR01/BR02 are authoritative when they are the active physical UI
            # branch. A forged body cannot redirect a physical branch write.
            if is_physical_branch(active):
                target = _canonical_branch(active)

            set_active_branch_id(target.pk)
            self._write_request_data_branch(request, target)

        else:
            # BR03 form-option requests deliberately pass ?branch=<BR01/BR02>.
            # Route those dependent reads to the selected physical database,
            # while a plain ?branch=BR03 list remains a combined read.
            raw = request.query_params.get("branch")
            candidate = _canonical_branch(raw) if raw not in (None, "", "all", "ALL") else None
            if is_physical_branch(candidate):
                set_active_branch_id(candidate.pk)

        return super().initial(request, *args, **kwargs)
