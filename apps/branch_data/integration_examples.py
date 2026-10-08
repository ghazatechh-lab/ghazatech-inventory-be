"""
Examples only: adapt these patterns inside the existing Ghazatech viewsets.
"""

from apps.sales.models import SalesInvoice
from apps.sales.serializers import SalesInvoiceSerializer

from .combined import combined_list
from .mixins import BranchDatabaseOperationMixin
from .routing import BR03


class ExampleInvoicePatterns(BranchDatabaseOperationMixin):
    def combined_invoice_response(self, request):
        branch = self.get_active_branch()

        if branch.branch_code != BR03:
            ctx = self.get_operation_context(write=False)
            qs = SalesInvoice.objects.using(ctx.db_alias).all()
            return SalesInvoiceSerializer(qs, many=True).data

        page = combined_list(
            vat_queryset=SalesInvoice.objects.all(),
            non_vat_queryset=SalesInvoice.objects.all(),
            serializer_class=SalesInvoiceSerializer,
            serializer_context={"request": request},
            source_filter=request.query_params.get("source_branch", "ALL"),
            ordering_key=lambda row: row.get("invoice_date") or "",
            page=request.query_params.get("page", 1),
            page_size=request.query_params.get("page_size", 20),
        )
        return {
            "count": page.count,
            "page": page.page,
            "page_size": page.page_size,
            "results": page.results,
        }
