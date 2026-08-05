import django_filters

from .models import StockTransfer


class StockTransferFilter(django_filters.FilterSet):
    branch = django_filters.NumberFilter(method="filter_branch")

    class Meta:
        model = StockTransfer
        fields = [
            "from_branch",
            "to_branch",
            "status",
            "branch",
        ]

    def filter_branch(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            django_filters.models.Q(from_branch_id=value)
            | django_filters.models.Q(to_branch_id=value)
        )
