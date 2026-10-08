from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.branches.models import Branch
from apps.branch_data.context import set_active_branch_id
from apps.branch_data.permissions import user_can_source
from apps.common.three_branch import ensure_branch_access

PHYSICAL_BRANCH_CODES = {"BR01", "BR02"}
COMBINED_BRANCH_CODE = "BR03"


def _canonical_branch(value):
    if value in (None, "", "all", "ALL"):
        return None
    qs = Branch.objects.using("default").filter(is_active=True)
    code = str(getattr(value, "branch_code", "") or "").strip().upper()
    if code:
        return qs.filter(branch_code__iexact=code).first()
    raw = getattr(value, "pk", value)
    text = str(raw or "").strip()
    if text.isdigit():
        return qs.filter(pk=int(text)).first()
    return qs.filter(branch_code__iexact=text).first()


def _request_value(request, key):
    try:
        value = request.data.get(key)
        if value not in (None, ""):
            return value
    except (AttributeError, TypeError):
        pass
    value = request.query_params.get(key)
    return value if value not in (None, "") else None


def _active_ui_branch(request):
    raw = (
        request.headers.get("X-Branch-ID")
        or request.query_params.get("active_branch")
        or request.query_params.get("branch")
    )
    return _canonical_branch(raw)


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
        branch_code__iexact=code,
        is_active=True,
    ).first()


def sale_mode_for_branch(branch):
    code = str(getattr(branch, "branch_code", "") or "").upper()
    if code == "BR01":
        return "VAT"
    if code == "BR02":
        return "NON_VAT"
    return ""


def requested_sales_target(request, *, allow_resource_key=True):
    """Resolve the real BR01/BR02 owner for a Sales operation.

    BR01/BR02 UI contexts are authoritative and cannot be redirected by a
    forged body. BR03 is virtual and must supply BR01/BR02 (or VAT/NON_VAT)
    when creating a new record. Existing BR03 detail/actions can derive the
    source from resource_key (VAT:id / NON_VAT:id).
    """
    active = _active_ui_branch(request)
    active_code = str(getattr(active, "branch_code", "") or "").upper()
    if active_code in PHYSICAL_BRANCH_CODES:
        return active

    raw = _request_value(request, "branch") or _request_value(request, "target_branch")
    candidate = _canonical_branch(raw)
    if candidate and str(candidate.branch_code).upper() in PHYSICAL_BRANCH_CODES:
        return candidate

    candidate = branch_from_source_value(raw)
    if candidate:
        return candidate

    if allow_resource_key:
        raw_lookup = ""
        # populated by the mixin from kwargs when relevant
        raw_lookup = getattr(request, "_sales_resource_key", "") or ""
        candidate = branch_from_source_value(raw_lookup)
        if candidate:
            return candidate
        candidate = branch_from_source_value(request.query_params.get("source_branch"))
        if candidate:
            return candidate

    return None


def require_sales_target(request):
    branch = requested_sales_target(request)
    if branch is None:
        raise serializers.ValidationError({
            "branch": (
                "Select Branch 1 or Branch 2. Branch 3 is a combined "
                "interface and cannot own sales data."
            )
        })
    return branch


class SalesPhysicalBranchGuardMixin:
    """Route Sales/Customer writes and Sales form reads to BR01/BR02.

    The selected physical branch is resolved before serializer validation so
    customer/product/invoice foreign keys are queried from the same database.
    """

    sales_write_methods = {"POST", "PUT", "PATCH"}

    @staticmethod
    def _mutate_request(request, branch, *, include_sale_mode=False):
        try:
            data = request.data
            old_mutable = getattr(data, "_mutable", None)
            if old_mutable is not None:
                data._mutable = True
            data["branch"] = branch.pk
            data["target_branch"] = branch.branch_code
            if include_sale_mode:
                data["sale_mode"] = sale_mode_for_branch(branch)
            if old_mutable is not None:
                data._mutable = old_mutable
        except Exception:
            pass

    def _model_has_field(self, name):
        model = getattr(getattr(self, "queryset", None), "model", None)
        if model is None:
            try:
                model = self.get_serializer_class().Meta.model
            except Exception:
                return False
        return name in {field.name for field in model._meta.get_fields()}

    def initial(self, request, *args, **kwargs):
        lookup_name = getattr(self, "lookup_url_kwarg", None) or getattr(self, "lookup_field", "pk")
        raw_lookup = self.kwargs.get(lookup_name) or self.kwargs.get("pk")
        try:
            request._sales_resource_key = raw_lookup
        except Exception:
            pass

        method = request.method.upper()
        if method in self.sales_write_methods:
            active = _active_ui_branch(request)
            if active is not None:
                ensure_branch_access(request.user, active)
            target = requested_sales_target(request)
            if target is None:
                target = require_sales_target(request)

            code = str(target.branch_code or "").upper()
            if code not in PHYSICAL_BRANCH_CODES:
                raise serializers.ValidationError({"branch": "Branch 3 cannot own sales data."})

            source = sale_mode_for_branch(target)
            active_code = str(getattr(active, "branch_code", "") or "").upper()
            if active_code == COMBINED_BRANCH_CODE and not user_can_source(
                request.user,
                source,
                write=True,
                action="create_sale",
            ):
                raise PermissionDenied(f"You do not have permission for {code} sales operations.")

            set_active_branch_id(target.pk)
            self._mutate_request(
                request,
                target,
                include_sale_mode=self._model_has_field("sale_mode"),
            )
        else:
            # Form-option/dependent reads from BR03 may pass either a physical
            # branch id or target_branch/sale_mode. Route those reads to the
            # physical database, while a plain BR03 list remains combined.
            raw = request.query_params.get("branch")
            candidate = _canonical_branch(raw)
            from_explicit_target = False
            if not (candidate and str(candidate.branch_code or "").upper() in PHYSICAL_BRANCH_CODES):
                explicit_target = (
                    request.query_params.get("target_branch")
                    or request.query_params.get("sale_mode")
                )
                candidate = branch_from_source_value(explicit_target)
                from_explicit_target = candidate is not None
            if candidate is None and raw_lookup:
                candidate = branch_from_source_value(raw_lookup)
            if candidate and str(candidate.branch_code or "").upper() in PHYSICAL_BRANCH_CODES:
                set_active_branch_id(candidate.pk)
                # Existing Sales form-option views commonly read ?branch=...
                # directly. When BR03 supplied target_branch/sale_mode, rewrite
                # only this request-local query value to the physical owner so
                # dependent customers/products/stock come from the same DB.
                if from_explicit_target:
                    try:
                        current = _canonical_branch(request.query_params.get("branch"))
                        if current and str(current.branch_code or "").upper() == COMBINED_BRANCH_CODE:
                            query = request._request.GET.copy()
                            query["branch"] = str(candidate.pk)
                            request._request.GET = query
                    except Exception:
                        pass

        return super().initial(request, *args, **kwargs)
