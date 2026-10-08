from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.branches.models import Branch

from .permissions import user_can_source
from .routing import (
    BR03,
    VAT,
    NON_VAT,
    resolve_operation_context,
)


class BranchDatabaseOperationMixin:
    """
    Drop-in helper for DRF views/viewsets.

    Expected existing project behavior:
      - request has access to the currently selected logical branch, OR
      - branch id/code is sent in request data/query params/header.

    Override get_active_branch() if your project stores active branch elsewhere.
    """

    permission_action = None

    def get_active_branch(self):
        request = self.request

        branch = getattr(request, "active_branch", None)
        if branch is not None:
            return branch

        raw = (
            request.data.get("branch")
            if hasattr(request, "data")
            else None
        ) or request.query_params.get("branch") or request.headers.get("X-Branch-ID")

        if not raw:
            raise ValidationError({"branch": "Select an active branch."})

        if str(raw).upper().startswith("BR"):
            return Branch.objects.get(branch_code=str(raw).upper())

        return Branch.objects.get(pk=raw)

    def get_permission_checker(self):
        user = self.request.user
        action = self.permission_action

        def checker(source, *, write=False):
            return user_can_source(
                user,
                source,
                write=write,
                action=action,
            )

        return checker

    def get_operation_context(self, *, write=False, target_branch=None):
        return resolve_operation_context(
            active_branch=self.get_active_branch(),
            target_branch=target_branch,
            request=self.request,
            permission_checker=self.get_permission_checker(),
            write=write,
        )

    def get_real_branch(self, context):
        return Branch.objects.get(branch_code=context.real_branch_code)

    def save_serializer_to_target(self, serializer, **extra):
        context = self.get_operation_context(write=True)
        real_branch = self.get_real_branch(context)

        # IMPORTANT:
        # DRF serializer.save(using=...) does NOT automatically route model save().
        # Pass the resolved branch to the serializer and execute the save while
        # the manager/queryset uses the requested DB, or override serializer.create.
        #
        # This helper supports serializers implementing:
        #   create_in_database(validated_data, using=..., branch=...)
        if hasattr(serializer, "create_in_database"):
            with transaction.atomic(using=context.db_alias):
                return serializer.create_in_database(
                    serializer.validated_data,
                    using=context.db_alias,
                    branch=real_branch,
                    source_branch=context.source_branch,
                    **extra,
                )

        raise NotImplementedError(
            "Serializer must implement create_in_database(..., using, branch, "
            "source_branch) for multi-database writes."
        )


class MultiDatabaseSerializerCreateMixin:
    """
    Add this to serializers that create transactional records.

    Override create_object_in_database() in serializers with nested writes.
    """

    def create_in_database(
        self,
        validated_data,
        *,
        using,
        branch,
        source_branch,
        **extra,
    ):
        validated_data = dict(validated_data)
        validated_data["branch"] = branch
        validated_data.pop("target_branch", None)

        return self.create_object_in_database(
            validated_data,
            using=using,
            source_branch=source_branch,
            **extra,
        )

    def create_object_in_database(
        self,
        validated_data,
        *,
        using,
        source_branch,
        **extra,
    ):
        model = self.Meta.model
        return model._default_manager.db_manager(using).create(**validated_data)
