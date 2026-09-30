from rest_framework.exceptions import ValidationError

from .services import database_alias_for_branch, mode_for_branch


class BranchDatabaseQuerysetMixin:
    """Use on branch-scoped DRF viewsets.

    Reads are sent to the database configured for the active branch.

    Branch resolution order:
    1. X-Branch-ID request header
    2. ?branch= query parameter
    3. branch value in request.data for POST/PUT/PATCH requests
    4. authenticated user's branch

    Writes are routed by BranchTransactionRouter. The router can use either
    the active branch context established by middleware or the branch attached
    to the model instance being saved.
    """

    branch_query_param = "branch"
    branch_payload_field = "branch"

    def _request_data_branch_id(self):
        request = getattr(self, "request", None)
        if request is None:
            return None

        method = str(getattr(request, "method", "") or "").upper()
        if method not in {"POST", "PUT", "PATCH"}:
            return None

        data = getattr(request, "data", None)
        if not data:
            return None

        try:
            value = data.get(self.branch_payload_field)
        except (AttributeError, TypeError):
            return None

        # Some clients may submit a small branch object instead of a raw PK.
        if isinstance(value, dict):
            value = value.get("id") or value.get("pk")

        return value

    def get_branch_id(self):
        request = getattr(self, "request", None)

        if request is None:
            return None

        value = (
            request.headers.get("X-Branch-ID")
            or request.query_params.get(self.branch_query_param)
            or self._request_data_branch_id()
        )

        if value in (None, "", "all", "ALL"):
            value = getattr(request.user, "branch_id", None)

        if value in (None, "", "all", "ALL"):
            return None

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"branch": "Invalid branch."}) from exc

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_id = self.get_branch_id()
        alias = database_alias_for_branch(branch_id)

        queryset = queryset.using(alias)

        if branch_id and hasattr(queryset.model, "branch_id"):
            queryset = queryset.filter(branch_id=branch_id)

        return queryset

    def get_database_alias(self):
        return database_alias_for_branch(self.get_branch_id())

    def get_database_mode(self):
        return mode_for_branch(self.get_branch_id())
