from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.deletion import CASCADE, PROTECT, ProtectedError

from rest_framework import status
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

    def _prepare_branch_for_permanent_delete(self, branch):
        """
        Prepare direct branch references before permanently deleting a branch.

        Nullable relations:
            Preserve the related record and remove its branch reference.

        CASCADE relations:
            Django handles them automatically.

        Non-null PROTECT relations:
            Delete the related branch-owned records.
        """

        for relation in branch._meta.related_objects:
            field = relation.field
            related_model = relation.related_model

            if not hasattr(field, "remote_field"):
                continue

            accessor_name = relation.get_accessor_name()

            if not accessor_name:
                continue

            try:
                related_manager = getattr(
                    branch,
                    accessor_name,
                )
            except AttributeError:
                continue

            if relation.one_to_one:
                try:
                    related_objects = [
                        related_manager,
                    ]
                except related_model.DoesNotExist:
                    related_objects = []
            else:
                related_objects = related_manager.all()

            on_delete = field.remote_field.on_delete

            # Preserve related record when branch is nullable.
            if field.null:
                if relation.one_to_one:
                    for obj in related_objects:
                        setattr(
                            obj,
                            field.name,
                            None,
                        )

                        obj.save(
                            update_fields=[
                                field.name,
                            ]
                        )
                else:
                    related_objects.update(
                        **{
                            field.name: None,
                        }
                    )

                continue

            # Django automatically handles CASCADE.
            if on_delete is CASCADE:
                continue

            # Delete mandatory PROTECT records.
            if on_delete is PROTECT:
                if relation.one_to_one:
                    for obj in related_objects:
                        obj.delete()
                else:
                    related_objects.delete()

    def destroy(self, request, *args, **kwargs):
        branch = self.get_object()

        force_delete = str(
            request.query_params.get(
                "force",
                "",
            )
        ).lower() in {
            "1",
            "true",
            "yes",
        }

        # -------------------------------------------------
        # Normal delete
        # -------------------------------------------------
        if not force_delete:
            try:
                branch.delete()

                return Response(
                    {
                        "success": True,
                        "message": ("Branch deleted successfully"),
                        "data": None,
                    },
                    status=status.HTTP_200_OK,
                )

            except ProtectedError as exc:
                protected_objects = list(exc.protected_objects)

                protected_preview = [
                    {
                        "model": (obj._meta.verbose_name.title()),
                        "value": str(obj),
                    }
                    for obj in protected_objects[:20]
                ]

                return Response(
                    {
                        "success": False,
                        "message": (
                            "This branch contains linked records. "
                            "Permanent deletion requires confirmation."
                        ),
                        "data": {
                            "confirmation_required": True,
                            "branch": {
                                "id": branch.id,
                                "branch_code": (branch.branch_code),
                                "branch_name": (branch.branch_name),
                            },
                            "protected_count": len(protected_objects),
                            "protected_records": (protected_preview),
                        },
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        # -------------------------------------------------
        # Confirmed permanent delete
        # -------------------------------------------------
        try:
            with transaction.atomic():
                branch_name = branch.branch_name
                branch_code = branch.branch_code

                self._prepare_branch_for_permanent_delete(branch)

                branch.delete()

            return Response(
                {
                    "success": True,
                    "message": (
                        f'Branch "{branch_name}" ' "permanently deleted successfully."
                    ),
                    "data": {
                        "branch_code": branch_code,
                        "permanently_deleted": True,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except ProtectedError as exc:
            remaining = [
                {
                    "model": (obj._meta.verbose_name.title()),
                    "value": str(obj),
                }
                for obj in list(exc.protected_objects)[:20]
            ]

            return Response(
                {
                    "success": False,
                    "message": (
                        "Some linked records could not be "
                        "deleted because they are protected "
                        "by other records."
                    ),
                    "data": {
                        "remaining_protected_records": (remaining),
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

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
        queryset = Branch.objects.filter(
            is_active=True,
        ).order_by(
            "branch_code",
            "branch_name",
        )

        if not can_switch_branches(request.user):
            branch_id = get_user_branch_id(request.user)

            queryset = queryset.filter(id=branch_id) if branch_id else queryset.none()

        return Response(
            {
                "success": True,
                "message": ("Branch selector options " "retrieved successfully"),
                "data": [
                    {
                        "id": branch.id,
                        "branch_code": (branch.branch_code),
                        "branch_name": (branch.branch_name),
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
                "message": ("Manager options retrieved " "successfully"),
                "data": serializer.data,
            }
        )
