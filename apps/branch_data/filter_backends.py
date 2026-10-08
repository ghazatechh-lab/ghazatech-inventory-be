from django_filters.rest_framework import DjangoFilterBackend

from .combined_views import is_combined_request


class VirtualBranchDjangoFilterBackend(DjangoFilterBackend):
    """Treat BR03 as BR01+BR02 for models that live on default.

    For secondary-database transaction apps the combined list mixin handles
    reads before this backend is used. For default/master apps, dropping only
    the BR03 branch parameter lets their existing querysets expose both
    physical branches without ever requiring BR03-owned rows.
    """

    SECONDARY_APPS = {"sales", "purchases", "customers", "suppliers", "finance", "shipments"}

    def get_filterset_kwargs(self, request, queryset, view):
        kwargs = super().get_filterset_kwargs(request, queryset, view)
        if not is_combined_request(request):
            return kwargs
        if queryset.model._meta.app_label in self.SECONDARY_APPS:
            return kwargs
        data = kwargs.get("data")
        if data is not None and "branch" in data:
            data = data.copy()
            data.pop("branch", None)
            kwargs["data"] = data
        return kwargs
