from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.branch_access import (
    can_switch_branches,
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
        Keep Branch Management itself restricted.

        Admins / branches.view_all can see all branch records.
        Other users see only their assigned branch here.

        The header selector uses selector-options instead.
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
        url_path="selector-options",
    )
    def selector_options(self, request):
        """
        Minimal branch options for the header selector.

        branches.switch:
            all active specific branches are returned.

        branches.view_all / admin:
            all active branches are returned and the frontend may also expose
            the "All branches" option.

        ordinary users:
            only their assigned branch is returned.
        """
        queryset = Branch.objects.filter(is_active=True).order_by(
            "branch_code",
            "branch_name",
        )

        if not can_switch_branches(request.user):
            branch_id = get_user_branch_id(request.user)
            queryset = queryset.filter(id=branch_id) if branch_id else queryset.none()

        return Response(
            {
                "success": True,
                "message": "Branch selector options retrieved successfully",
                "data": [
                    {
                        "id": branch.id,
                        "branch_code": branch.branch_code,
                        "branch_name": branch.branch_name,
                    }
                    for branch in queryset
                ],
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="manager-options",
    )
    def manager_options(self, request):
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
                queryset = queryset.filter(branch_id=branch_id)
            elif hasattr(User, "employee"):
                queryset = queryset.filter(employee__branch_id=branch_id)

        serializer = BranchManagerOptionSerializer(
            queryset,
            many=True,
        )

        return Response(
            {
                "success": True,
                "message": "Manager options retrieved successfully",
                "data": serializer.data,
            }
        )
