from rest_framework.permissions import BasePermission

from .permission_helpers import (
    has_erp_permission,
    is_admin_user,
)
from .route_permission_rules import (
    resolve_permission_code,
)


class ERPProjectPermission(BasePermission):
    """
    Global project-wide permission enforcement.

    Add to REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES after IsAuthenticated.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if is_admin_user(user):
            return True

        explicit_permission = getattr(
            view,
            "required_permission",
            None,
        )

        permission_map = (
            getattr(
                view,
                "permission_map",
                None,
            )
            or {}
        )

        action = getattr(view, "action", None)

        permission_code = (
            permission_map.get(action)
            or permission_map.get(request.method.upper())
            or explicit_permission
            or resolve_permission_code(request)
        )

        if not permission_code:
            # Authenticated endpoints not yet in the catalogue continue to work.
            # Set ERP_PERMISSION_STRICT=True to deny unmapped endpoints.
            from django.conf import settings

            return not getattr(
                settings,
                "ERP_PERMISSION_STRICT",
                False,
            )

        request.required_permission = permission_code

        return has_erp_permission(
            user,
            permission_code,
        )
