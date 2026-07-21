from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Global API pagination for every listing endpoint."""

    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 500
