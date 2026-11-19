from rest_framework.permissions import BasePermission

from apps.accounts.permissions import permissions_for


class HasPlatformPermission(BasePermission):
    """
    Checks the platform permission matrix.

    Set on a view::

        required_permission = "admin.users.view"
        # or one per HTTP method:
        required_permissions = {"GET": "admin.users.view", "POST": "admin.accounts.freeze"}
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        per_method = getattr(view, "required_permissions", None)
        method = "GET" if request.method == "HEAD" else request.method
        needed = per_method.get(method) if per_method else getattr(view, "required_permission", None)
        if needed is None:
            # Fail closed: a view using this class must declare what it needs.
            return False
        return needed in permissions_for(user)
