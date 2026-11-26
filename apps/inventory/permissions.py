from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsBranchUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class ReferenceDataPermission(BasePermission):
    """Respect the inventory permissions configured for each user.

    Some inventory endpoints override global DRF permissions with this class,
    so checking only for admin status would discard explicitly granted CRUD.
    """
    message = "Your account does not have permission for this inventory operation."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or getattr(getattr(user, "role", None), "code", "") == "ADMIN":
            return True

        action = getattr(view, "action", None)
        if action in ("list", "retrieve") or request.method in SAFE_METHODS:
            operation = "view"
        elif action in ("create",) or request.method == "POST" and action == "create":
            operation = "create"
        elif action in ("update", "partial_update") or request.method in ("PUT", "PATCH"):
            operation = "edit"
        elif action == "destroy" or request.method == "DELETE":
            operation = "delete"
        else:
            # Custom actions keep their own authorization checks (e.g. rack
            # reconciliation is superuser-only) and use explicit permissions.
            operation = action or "view"

        model = getattr(getattr(view, "serializer_class", None), "Meta", None)
        resource_by_name = {"Brand": "brands", "Category": "categories", "Rack": "racks"}
        model_name = getattr(getattr(model, "model", None), "__name__", "")
        resource = resource_by_name.get(model_name)
        if resource is None:
            # rack-allocation special actions are verified inside the view.
            resource = "racks"
        has = getattr(user, "has_operation_permission", None)
        return bool(has and has(f"inventory.{resource}.{operation}"))
