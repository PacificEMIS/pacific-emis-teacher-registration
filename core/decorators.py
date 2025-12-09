"""
Access control decorators for Pacific EMIS views.

This module provides decorators to enforce Layer 1 (App-Level Access) of the
access control system. These decorators ensure users have the proper profile
and group membership before accessing views.

Access Control Layers:
---------------------
Layer 1 (App-Level): Enforced by decorators in this module
  - User must be authenticated (@login_required)
  - User must have SchoolStaff OR SystemUser profile
  - User must belong to at least one group

Layer 2 (Row-Level): Enforced by permission functions in core.permissions
  - Data filtered based on user's school assignments or group permissions

Decorators:
----------
@require_app_access
    Basic access control - user must have profile + group
    Use this on all views that require authentication

@require_role_and_group(GROUP_ADMINS, GROUP_TEACHERS, ...)
    Granular access control - user must be in specific groups
    Use this for views that require specific permissions

Usage Examples:
--------------
    from django.contrib.auth.decorators import login_required
    from core.decorators import require_app_access
    from core.permissions import GROUP_ADMINS, GROUP_TEACHERS

    # Basic access - any user with profile + group can access
    @login_required
    @require_app_access
    def dashboard(request):
        ...

    # Restricted access - only Admins and Teachers can access
    @login_required
    @require_role_and_group(GROUP_ADMINS, GROUP_TEACHERS)
    def create_student(request):
        ...

See README.md and core.permissions for complete documentation.
"""
from functools import wraps
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied

from core.permissions import has_app_access


def require_app_access(view_func):
    """
    Decorator to require that the user has app access.

    User must:
    1. Be authenticated
    2. Have either SchoolStaff or SystemUser profile
    3. Be a member of at least one group

    If user doesn't have access, redirects to no_permissions page.

    Usage:
        @login_required
        @require_app_access
        def my_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not has_app_access(request.user):
            return redirect('accounts:no_permissions')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_role_and_group(*allowed_groups):
    """
    Decorator to require specific group membership.

    User must:
    1. Have app access (profile + group)
    2. Be a member of at least one of the specified groups

    Args:
        *allowed_groups: Group names that are allowed access

    Raises:
        PermissionDenied if user is not in any of the allowed groups

    Usage:
        from core.permissions import GROUP_ADMINS, GROUP_TEACHERS

        @login_required
        @require_role_and_group(GROUP_ADMINS, GROUP_TEACHERS)
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user

            # First check app access
            if not has_app_access(user):
                return redirect('accounts:no_permissions')

            # Then check group membership
            if user.is_superuser:
                return view_func(request, *args, **kwargs)

            if not user.groups.filter(name__in=allowed_groups).exists():
                raise PermissionDenied

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
