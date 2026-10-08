from __future__ import annotations

from django.db.models import Q
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.branches.models import Branch
from .combined import add_source_metadata

PHYSICAL_SOURCES = (
    ("VAT", "vat", "BR01"),
    ("NON_VAT", "non_vat", "BR02"),
)


def requested_branch(request):
    raw = request.query_params.get("branch") or request.headers.get("X-Branch-ID")
    if not raw:
        return None
    qs = Branch.objects.using("default").filter(is_active=True)
    text = str(raw).strip()
    if text.isdigit():
        return qs.filter(pk=int(text)).first()
    return qs.filter(branch_code__iexact=text).first()


def physical_branches():
    rows = {
        b.branch_code.upper(): b
        for b in Branch.objects.using("default").filter(
            branch_code__in=["BR01", "BR02"], is_active=True
        )
    }
    return rows


def is_combined_request(request):
    branch = requested_branch(request)
    return bool(branch and str(branch.branch_code).upper() == "BR03")


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class CombinedPhysicalBranchListMixin:
    """Combine VAT + NON_VAT database rows when BR03 is the active branch.

    This mixin is for models whose business rows physically live in the
    secondary databases. It intentionally changes list/retrieve reads only;
    writes continue through the existing branch/target routing.
    """

    combined_branch_field = "branch"
    combined_default_ordering = "-id"

    def _base_combined_queryset(self, alias, branch_id):
        model = self.get_serializer_class().Meta.model
        configured = getattr(self, "queryset", None)
        qs = (configured.all() if configured is not None else model._default_manager.all()).using(alias)
        field = self.combined_branch_field
        if field:
            qs = qs.filter(**{f"{field}_id": branch_id})
        return qs

    def _apply_combined_filters(self, qs):
        params = self.request.query_params
        model = qs.model
        field_names = {f.name for f in model._meta.get_fields()}

        for field in getattr(self, "filterset_fields", []) or []:
            if not isinstance(field, str) or field == "branch":
                continue
            if field not in params or field not in field_names:
                continue
            value = params.get(field)
            if value not in (None, "", "all", "ALL"):
                qs = qs.filter(**{field: value})

        search = params.get("search") or params.get("q")
        if search:
            search_q = Q()
            for field in getattr(self, "search_fields", []) or []:
                clean = str(field).lstrip("^=@$")
                try:
                    search_q |= Q(**{f"{clean}__icontains": search})
                except Exception:
                    continue
            if search_q.children:
                qs = qs.filter(search_q)

        ordering = params.get("ordering") or getattr(self, "ordering", None)
        if isinstance(ordering, (list, tuple)):
            ordering_fields = list(ordering)
        elif ordering:
            ordering_fields = [x.strip() for x in str(ordering).split(",") if x.strip()]
        else:
            ordering_fields = [self.combined_default_ordering]
        try:
            qs = qs.order_by(*ordering_fields)
        except Exception:
            qs = qs.order_by(self.combined_default_ordering)
        return qs

    def combined_querysets(self):
        """Return routed BR01/BR02 querysets for BR03 custom aggregate actions."""
        if not is_combined_request(self.request):
            return None

        source_filter = str(
            self.request.query_params.get("source_branch") or "ALL"
        ).upper().replace("-", "_")
        source_filter = {
            "BR01": "VAT",
            "BR02": "NON_VAT",
            "BRANCH_1": "VAT",
            "BRANCH_2": "NON_VAT",
        }.get(source_filter, source_filter)
        if source_filter not in {"ALL", "VAT", "NON_VAT"}:
            raise ValidationError({"source_branch": "Use ALL, BR01, or BR02."})

        branches = physical_branches()
        result = []
        for source, alias, code in PHYSICAL_SOURCES:
            if source_filter not in {"ALL", source}:
                continue
            branch = branches.get(code)
            if not branch:
                continue
            qs = self._base_combined_queryset(alias, branch.id)
            qs = self._apply_combined_filters(qs)
            result.append((source, alias, branch, qs))
        return result

    def list(self, request, *args, **kwargs):
        if not is_combined_request(request):
            return super().list(request, *args, **kwargs)

        model = self.get_serializer_class().Meta.model
        model_fields = {field.name for field in model._meta.get_fields()}
        if self.combined_branch_field and self.combined_branch_field not in model_fields:
            # Shared/reference models inside a transaction app remain readable
            # from the default database and must not be duplicated across VAT
            # and NON_VAT sources.
            return super().list(request, *args, **kwargs)

        source_filter = str(request.query_params.get("source_branch") or "ALL").upper().replace("-", "_")
        source_filter = {"BR01": "VAT", "BR02": "NON_VAT", "BRANCH_1": "VAT", "BRANCH_2": "NON_VAT"}.get(source_filter, source_filter)
        if source_filter not in {"ALL", "VAT", "NON_VAT"}:
            raise ValidationError({"source_branch": "Use ALL, BR01, or BR02."})

        branches = physical_branches()
        rows = []
        for source, alias, code in PHYSICAL_SOURCES:
            if source_filter not in {"ALL", source}:
                continue
            branch = branches.get(code)
            if not branch:
                continue
            qs = self._base_combined_queryset(alias, branch.id)
            qs = self._apply_combined_filters(qs)
            serializer = self.get_serializer(qs, many=True)
            rows.extend(
                add_source_metadata(
                    row,
                    source_branch=source,
                    branch_id=branch.id,
                    branch_code=code,
                )
                for row in serializer.data
            )

        ordering = request.query_params.get("ordering") or "-id"
        reverse = str(ordering).startswith("-")
        key = str(ordering).lstrip("-").split(",", 1)[0]
        rows.sort(key=lambda r: (r.get(key) is not None, r.get(key)), reverse=reverse)

        page_size = max(1, min(_safe_int(request.query_params.get("page_size"), 20), 500))
        page = max(1, _safe_int(request.query_params.get("page"), 1))
        start = (page - 1) * page_size
        end = start + page_size
        return Response({
            "count": len(rows),
            "next": None,
            "previous": None,
            "results": rows[start:end],
        })

    def _combined_object_source(self):
        raw_pk = str(self.kwargs.get(self.lookup_url_kwarg or self.lookup_field, ""))
        source = str(self.request.query_params.get("source_branch") or "").upper().replace("-", "_")
        record_id = raw_pk
        if ":" in raw_pk:
            source, record_id = raw_pk.split(":", 1)
            source = source.upper().replace("-", "_")
        if source not in {"VAT", "NON_VAT"}:
            raise ValidationError({
                "source_branch": "BR03 detail/action reads require resource_key (VAT:id / NON_VAT:id) or source_branch."
            })
        return source, record_id

    def get_object(self):
        if not is_combined_request(self.request):
            return super().get_object()
        source, record_id = self._combined_object_source()
        alias = "vat" if source == "VAT" else "non_vat"
        code = "BR01" if source == "VAT" else "BR02"
        branch = physical_branches().get(code)
        qs = self._base_combined_queryset(alias, branch.id)
        obj = qs.filter(pk=record_id).first()
        if obj is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Record not found in the selected source branch.")
        self.check_object_permissions(self.request, obj)
        return obj

    def retrieve(self, request, *args, **kwargs):
        if not is_combined_request(request):
            return super().retrieve(request, *args, **kwargs)

        source, _record_id = self._combined_object_source()
        obj = self.get_object()
        alias = "vat" if source == "VAT" else "non_vat"
        code = "BR01" if source == "VAT" else "BR02"
        branch = physical_branches().get(code)
        data = self.get_serializer(obj).data
        return Response(add_source_metadata(data, source_branch=source, branch_id=branch.id, branch_code=code))


class DefaultCombinedBranchRequestMixin:
    """For apps stored on default, BR03 means all physical branch rows.

    Existing views often implement manual `if branch: filter(branch_id=branch)`
    logic. Removing only the query-string branch value for BR03 lets those
    established views naturally return BR01 + BR02 without creating virtual
    BR03-owned rows. The X-Branch-ID header is left intact for permissions and
    context.
    """

    def initial(self, request, *args, **kwargs):
        raw = request.query_params.get("branch")
        if raw:
            qs = Branch.objects.using("default").filter(is_active=True)
            text = str(raw).strip()
            branch = qs.filter(pk=int(text)).first() if text.isdigit() else qs.filter(branch_code__iexact=text).first()
            if branch and str(branch.branch_code).upper() == "BR03":
                try:
                    data = request._request.GET.copy()
                    data.pop("branch", None)
                    request._request.GET = data
                except Exception:
                    pass
        return super().initial(request, *args, **kwargs)
