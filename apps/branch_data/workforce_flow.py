from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.branches.models import Branch

PHYSICAL_CODES = ("BR01", "BR02")
SOURCE_TO_CODE = {
    "BR01": "BR01",
    "BR02": "BR02",
    "VAT": "BR01",
    "NON_VAT": "BR02",
}


def _branch_qs():
    return Branch.objects.using("default").filter(is_active=True)


def branch_from_value(value):
    if value in (None, "", "all", "ALL"):
        return None
    if isinstance(value, dict):
        value = value.get("id") or value.get("branch_id") or value.get("branch_code")
    else:
        value = getattr(value, "pk", None) or getattr(value, "branch_code", None) or value
    text = str(value).strip()
    qs = _branch_qs()
    if text.isdigit():
        return qs.filter(pk=int(text)).first()
    return qs.filter(branch_code__iexact=text).first()


def active_interface_branch(request):
    """Resolve the global active branch.

    Header wins over query params because BR03 create screens may use ?branch=<BR01/BR02>
    to load target-specific form options while the active interface remains BR03.
    """
    if request is None:
        return None
    headers = getattr(request, "headers", {}) or {}
    query = getattr(request, "query_params", {}) or {}
    raw = headers.get("X-Branch-ID") or headers.get("X-Branch-Id") or query.get("branch")
    return branch_from_value(raw)


def is_physical(branch):
    return bool(branch and str(branch.branch_code or "").upper() in PHYSICAL_CODES)


def is_combined(branch):
    return bool(branch and str(branch.branch_code or "").upper() == "BR03")


def physical_branches():
    rows = _branch_qs().filter(branch_code__in=PHYSICAL_CODES).order_by("branch_code")
    return list(rows)


def _source_branch(request):
    raw = str((getattr(request, "query_params", {}) or {}).get("source_branch") or "ALL").upper().replace("-", "_")
    if raw == "ALL":
        return None
    code = SOURCE_TO_CODE.get(raw)
    if not code:
        raise ValidationError({"source_branch": "Use ALL, BR01, or BR02."})
    return _branch_qs().filter(branch_code=code).first()


def scope_queryset(request, queryset, lookup="branch_id"):
    """Apply BR01/BR02 isolation or BR03 combined/source filtering."""
    active = active_interface_branch(request)
    if not active:
        return queryset

    code = str(active.branch_code or "").upper()
    if code in PHYSICAL_CODES:
        return queryset.filter(**{lookup: active.pk})

    if code == "BR03":
        selected = _source_branch(request)
        if selected:
            return queryset.filter(**{lookup: selected.pk})
        ids = list(
            _branch_qs().filter(branch_code__in=PHYSICAL_CODES).values_list("pk", flat=True)
        )
        return queryset.filter(**{f"{lookup}__in": ids})

    return queryset.none()


def require_direct_write_branch(request, supplied=None, *, existing=None):
    """Resolve a direct owner (Employee, PayrollRun, Vehicle) to BR01/BR02."""
    active = active_interface_branch(request)
    if not active:
        raise ValidationError({"branch": "Select an active physical branch."})

    if is_physical(active):
        requested = branch_from_value(supplied)
        if requested and requested.pk != active.pk:
            raise ValidationError({"branch": f"Current branch is {active.branch_code}; another branch cannot be used."})
        return active

    if not is_combined(active):
        raise ValidationError({"branch": "Only Branch 1 or Branch 2 can own this record."})

    # On BR03, direct-owner writes must be explicit even for updates.
    target = branch_from_value(supplied)
    if not is_physical(target):
        raise ValidationError({"branch": "Branch 3 cannot own records. Select Branch 1 or Branch 2."})
    return target


def require_related_branch(request, related_branch):
    """Validate employee/vehicle inherited ownership against the active interface."""
    if not is_physical(related_branch):
        raise ValidationError({"branch": "The related employee/vehicle must belong to Branch 1 or Branch 2."})

    active = active_interface_branch(request)
    if not active:
        raise ValidationError({"branch": "Select an active branch."})

    if is_physical(active) and active.pk != related_branch.pk:
        raise ValidationError({"branch": f"This record belongs to {related_branch.branch_code}, not the current branch."})

    if not (is_physical(active) or is_combined(active)):
        raise ValidationError({"branch": "Only Branch 1 or Branch 2 may own this record."})
    return related_branch


class WorkforceBranchScopeMixin:
    """Shared default-DB branch isolation for HRMS/Fleet viewsets."""

    branch_scope_lookup = None
    direct_branch_owner = False
    related_branch_field = None

    def _auto_scope_lookup(self, queryset):
        if self.branch_scope_lookup:
            return self.branch_scope_lookup
        names = {field.name for field in queryset.model._meta.get_fields()}
        if "branch" in names:
            return "branch_id"
        if "employee" in names:
            return "employee__branch_id"
        if "vehicle" in names:
            return "vehicle__branch_id"
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        lookup = self._auto_scope_lookup(queryset)
        return scope_queryset(self.request, queryset, lookup) if lookup else queryset

    def _related_branch(self, serializer, instance=None):
        field = self.related_branch_field
        if not field:
            model_fields = {f.name for f in serializer.Meta.model._meta.get_fields()}
            field = "employee" if "employee" in model_fields else ("vehicle" if "vehicle" in model_fields else None)
        if not field:
            return None
        related = serializer.validated_data.get(field) or getattr(instance, field, None)
        return getattr(related, "branch", None) if related else None

    def perform_create(self, serializer):
        if self.direct_branch_owner:
            target = require_direct_write_branch(self.request, serializer.validated_data.get("branch"))
            serializer.save(branch=target)
            return

        related_branch = self._related_branch(serializer)
        if related_branch:
            target = require_related_branch(self.request, related_branch)
            model_fields = {f.name for f in serializer.Meta.model._meta.get_fields()}
            if "branch" in model_fields:
                serializer.save(branch=target)
            else:
                serializer.save()
            return
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if self.direct_branch_owner:
            target = require_direct_write_branch(
                self.request,
                serializer.validated_data.get("branch"),
                existing=getattr(instance, "branch", None),
            )
            serializer.save(branch=target)
            return

        related_branch = self._related_branch(serializer, instance=instance)
        if related_branch:
            target = require_related_branch(self.request, related_branch)
            model_fields = {f.name for f in serializer.Meta.model._meta.get_fields()}
            if "branch" in model_fields:
                serializer.save(branch=target)
            else:
                serializer.save()
            return
        serializer.save()
