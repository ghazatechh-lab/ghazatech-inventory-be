from rest_framework.permissions import BasePermission, SAFE_METHODS


def is_admin_user(user):
    if not user or not user.is_authenticated:
        return False
    role_code = getattr(getattr(user, "role", None), "code", "")
    return bool(user.is_superuser or role_code == "ADMIN")


class IsBranchUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class ReferenceDataPermission(BasePermission):
    """All authenticated users may list/retrieve/create; only Admin may update/delete."""

    message = "Only Admin can edit or delete this inventory reference record."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS or request.method == "POST":
            return True
        return is_admin_user(request.user)
