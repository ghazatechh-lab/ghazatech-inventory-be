import json

from django.http import JsonResponse

from .context import reset_active_branch_id, set_active_branch_id


class BranchDatabaseContextMiddleware:
    """Resolve the active branch before database routing occurs.

    The frontend should send X-Branch-ID on every branch-scoped request.
    Query-string and request-body fallbacks keep create/update requests safe
    when a client sends the branch only as form/JSON data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _normalize_branch_id(value):
        if isinstance(value, dict):
            value = value.get("id") or value.get("pk")

        if value in (None, "", "all", "ALL"):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _body_branch_id(request):
        if request.method not in {"POST", "PUT", "PATCH"}:
            return None

        content_type = str(request.content_type or "").lower()

        if "application/json" in content_type:
            try:
                payload = json.loads((request.body or b"{}").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None

            if isinstance(payload, dict):
                return payload.get("branch")
            return None

        # Django can safely parse standard form and multipart form payloads here.
        try:
            return request.POST.get("branch")
        except Exception:
            return None

    def __call__(self, request):
        raw_branch_id = (
            request.headers.get("X-Branch-ID")
            or request.GET.get("branch")
            or self._body_branch_id(request)
        )

        branch_id = self._normalize_branch_id(raw_branch_id)

        if branch_id is False:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid branch.",
                    "data": None,
                },
                status=400,
            )

        token = set_active_branch_id(branch_id)
        try:
            return self.get_response(request)
        finally:
            reset_active_branch_id(token)
