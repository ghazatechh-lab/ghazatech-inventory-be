from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.branch_access import (
    can_view_all_branches,
    get_user_branch_id,
)
from apps.common.logging import (
    LoggedModelViewSet as ModelViewSet,
)

from .models import Branch
from .serializers import (
    BranchManagerOptionSerializer,
    BranchSerializer,
)

User = get_user_model()


class BranchViewSet(ModelViewSet):
    queryset = Branch.objects.select_related(
        "manager",
        "manager__role",
    ).all()
    serializer_class = BranchSerializer
    search_fields = [
        "branch_code",
        "branch_name",
        "city",
    ]
    filterset_fields = [
        "is_active",
        "emirate",
    ]

    def get_queryset(self):
        """
        Admins and users with `branches.view_all` can see all branches.

        Other users can see only their assigned branch.
        """
        queryset = super().get_queryset()
        user = self.request.user

        if can_view_all_branches(user):
            return queryset

        branch_id = get_user_branch_id(user)

        if not branch_id:
            return queryset.none()

        return queryset.filter(id=branch_id)

    @action(
        detail=False,
        methods=["get"],
        url_path="manager-options",
    )
    def manager_options(self, request):
        """
        Return active users that can be selected as branch managers.

        Users without `branches.view_all` receive only users assigned
        to their own branch where that relation is available.
        """
        queryset = (
            User.objects.filter(is_active=True)
            .select_related("role")
            .order_by(
                "full_name",
                "username",
                "email",
            )
        )

        if not can_view_all_branches(request.user):
            branch_id = get_user_branch_id(request.user)

            if not branch_id:
                queryset = queryset.none()
            elif hasattr(User, "branch"):
                queryset = queryset.filter(
                    branch_id=branch_id,
                )
            elif hasattr(User, "employee"):
                queryset = queryset.filter(
                    employee__branch_id=branch_id,
                )

        serializer = BranchManagerOptionSerializer(
            queryset,
            many=True,
        )

        return Response(
            {
                "success": True,
                "message": ("Manager options retrieved successfully"),
                "data": serializer.data,
            }
        )
