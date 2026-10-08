from django.utils.deprecation import MiddlewareMixin

from apps.branches.models import Branch

from .context import reset_branch_context, set_branch_context
from .routing import (
    COMBINED,
    source_for_active_branch,
    database_for_source,
    get_request_target,
    normalize_branch_code,
)


class BranchDatabaseContextMiddleware(MiddlewareMixin):
    """
    Establishes DB context for BR01/BR02 requests.

    BR03 is intentionally NOT assigned a database automatically. Reads from
    BR03 must use combined services, and writes must explicitly resolve a
    target branch in the view/serializer.
    """

    def process_request(self, request):
        branch = getattr(request, "active_branch", None)

        if branch is None:
            raw = (
                request.headers.get("X-Branch-ID")
                or request.GET.get("branch")
            )
            if raw:
                try:
                    branch = (
                        Branch.objects.get(branch_code=str(raw).upper())
                        if str(raw).upper().startswith("BR")
                        else Branch.objects.get(pk=raw)
                    )
                except (Branch.DoesNotExist, ValueError):
                    branch = None

        request.active_branch = branch
        code = normalize_branch_code(branch)
        source = source_for_active_branch(code)

        db_alias = None
        if source and source != COMBINED:
            db_alias = database_for_source(source)

        request._ghaza_context_tokens = set_branch_context(
            db_alias=db_alias,
            source_branch=source,
            active_branch_code=code,
        )

    def process_response(self, request, response):
        tokens = getattr(request, "_ghaza_context_tokens", None)
        if tokens:
            reset_branch_context(tokens)
        return response

    def process_exception(self, request, exception):
        tokens = getattr(request, "_ghaza_context_tokens", None)
        if tokens:
            reset_branch_context(tokens)
        return None
