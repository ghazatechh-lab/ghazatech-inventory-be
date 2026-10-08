from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from apps.branches.models import Branch

from .routing import VAT, NON_VAT, make_resource_key


@dataclass
class CombinedPage:
    count: int
    page: int
    page_size: int
    results: list


def add_source_metadata(row, *, source_branch, branch_id=None, branch_code=None):
    data = dict(row)
    record_id = data.get("id")
    data["source_branch"] = source_branch
    data["source_branch_id"] = branch_id
    data["source_branch_code"] = branch_code
    if record_id is not None:
        data["resource_key"] = make_resource_key(source_branch, record_id)
    return data


def serialize_queryset(
    queryset,
    *,
    serializer_class,
    source_branch,
    branch_id=None,
    branch_code=None,
    serializer_context=None,
):
    serializer = serializer_class(
        queryset,
        many=True,
        context=serializer_context or {},
    )
    return [
        add_source_metadata(
            row,
            source_branch=source_branch,
            branch_id=branch_id,
            branch_code=branch_code,
        )
        for row in serializer.data
    ]


def merge_rows(
    vat_rows: Sequence[dict],
    non_vat_rows: Sequence[dict],
    *,
    ordering_key: Callable[[dict], object] | None = None,
    reverse=True,
    page=1,
    page_size=20,
):
    rows = list(vat_rows) + list(non_vat_rows)
    if ordering_key is not None:
        rows.sort(key=ordering_key, reverse=reverse)

    page = max(int(page or 1), 1)
    page_size = max(min(int(page_size or 20), 500), 1)
    start = (page - 1) * page_size
    end = start + page_size
    return CombinedPage(
        count=len(rows),
        page=page,
        page_size=page_size,
        results=rows[start:end],
    )


def combined_list(
    *,
    vat_queryset,
    non_vat_queryset,
    serializer_class,
    serializer_context=None,
    source_filter="ALL",
    ordering_key=None,
    reverse=True,
    page=1,
    page_size=20,
    vat_branch_id=None,
    non_vat_branch_id=None,
):
    source_filter = str(source_filter or "ALL").upper().replace("-", "_")

    if vat_branch_id is None:
        vat_branch_id = (
            Branch.objects.using("default")
            .filter(branch_code__iexact="BR01", is_active=True)
            .values_list("id", flat=True)
            .first()
        )

    if non_vat_branch_id is None:
        non_vat_branch_id = (
            Branch.objects.using("default")
            .filter(branch_code__iexact="BR02", is_active=True)
            .values_list("id", flat=True)
            .first()
        )

    if vat_branch_id is None:
        raise RuntimeError("Active BR01 branch was not found.")

    if non_vat_branch_id is None:
        raise RuntimeError("Active BR02 branch was not found.")

    vat_rows = []
    non_vat_rows = []

    if source_filter in {"ALL", VAT}:
        vat_rows = serialize_queryset(
            vat_queryset.using("vat"),
            serializer_class=serializer_class,
            source_branch=VAT,
            branch_id=vat_branch_id,
            branch_code="BR01",
            serializer_context=serializer_context,
        )

    if source_filter in {"ALL", NON_VAT}:
        non_vat_rows = serialize_queryset(
            non_vat_queryset.using("non_vat"),
            serializer_class=serializer_class,
            source_branch=NON_VAT,
            branch_id=non_vat_branch_id,
            branch_code="BR02",
            serializer_context=serializer_context,
        )

    return merge_rows(
        vat_rows,
        non_vat_rows,
        ordering_key=ordering_key,
        reverse=reverse,
        page=page,
        page_size=page_size,
    )
