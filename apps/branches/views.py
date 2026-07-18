from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.logging import LoggedModelViewSet as ModelViewSet
from .models import Branch
from .serializers import BranchManagerOptionSerializer, BranchSerializer

User = get_user_model()


class BranchViewSet(ModelViewSet):
    queryset = Branch.objects.select_related("manager", "manager__role").all()
    serializer_class = BranchSerializer
    search_fields = ["branch_code", "branch_name", "city"]
    filterset_fields = ["is_active", "emirate"]

    @action(detail=False, methods=["get"], url_path="manager-options")
    def manager_options(self, request):
        """Return active users that can be selected as a branch manager."""
        queryset = (
            User.objects.filter(is_active=True)
            .select_related("role")
            .order_by("full_name", "username", "email")
        )

        serializer = BranchManagerOptionSerializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "message": "Manager options retrieved successfully",
                "data": serializer.data,
            }
        )
