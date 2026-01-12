"""
Access control and permissions for the Pacific EMIS system.

This module implements a two-layer access control system:

Layer 1: App-Level Access (Profile + Group)
-------------------------------------------
Enforced by @require_app_access decorator in core.decorators.
Users must have:
  1. Authentication (login)
  2. Profile (SchoolStaff OR SystemUser)
  3. Group membership (at least one group)

Without all three, users see the "no permissions" page.

Layer 2: Row-Level Access (School-based filtering)
--------------------------------------------------
Enforced by permission functions in this module.
- Admins/System Admins: See all data
- SchoolStaff groups: See only data from their assigned schools
- SystemUser groups: See all data (system-wide access)

Permission Groups
-----------------
School-Level (for SchoolStaff users):
  - Admins: System-wide full access
  - School Admins: School-scoped admin (can manage their schools)
  - Teachers: School-scoped access for teachers
  - School Staff: Read-only at their schools

System-Level (for SystemUser users):
  - System Admins: System-wide full access
  - System Staff: System-wide read-only access

Usage Example
-------------
    from core.decorators import require_app_access
    from core.permissions import (
        has_app_access, is_admin
    )

    @login_required
    @require_app_access  # Ensures user has profile + group
    def my_view(request):
        # User has app access, now check specific permissions
        if is_admin(request.user):
            # Allow admin operations
            pass

See README.md for complete access control architecture documentation.
"""
from django.contrib.auth.models import Group
from django.db.models import Q
from django.db.models import QuerySet


from integrations.models import EmisSchool

# ---- Group names (single source of truth) ----

# School-level groups (for SchoolStaff users)
GROUP_ADMINS = "Admins"
GROUP_SCHOOL_ADMINS = "School Admins"
GROUP_SCHOOL_STAFF = "School Staff"
GROUP_TEACHERS = "Teachers"

# System-level groups (for SystemUser users)
GROUP_SYSTEM_ADMINS = "System Admins"
GROUP_SYSTEM_STAFF = "System Staff"

# Legacy names for backward compatibility (deprecated - remove after migration)
GROUP_INCLUSIVE_ADMINS = GROUP_ADMINS
GROUP_INCLUSIVE_SCHOOL_ADMINS = GROUP_SCHOOL_ADMINS
GROUP_INCLUSIVE_STAFF = GROUP_SCHOOL_STAFF
GROUP_INCLUSIVE_TEACHERS = GROUP_TEACHERS

# ---- Role helpers -----------------------------------------------------------


def _in_group(user, group_name: str) -> bool:
    """Check if user is in the specified group."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def is_admin(user) -> bool:
    """
    System-wide admins (plus superusers) have full access to everything.
    This includes both 'Admins' and 'System Admins' groups.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_group(user, GROUP_ADMINS) or _in_group(user, GROUP_SYSTEM_ADMINS)


def is_school_staff(user) -> bool:
    """School Staff: Read-only access, per-school restricted."""
    return _in_group(user, GROUP_SCHOOL_STAFF)


def is_school_admin(user) -> bool:
    """School Admins: School-scoped admin; can manage staff/data at their schools."""
    return _in_group(user, GROUP_SCHOOL_ADMINS)


def is_teacher(user) -> bool:
    """Teachers: Per-school restricted access."""
    return _in_group(user, GROUP_TEACHERS)


def is_system_staff(user) -> bool:
    """System Staff: Read-only access, system-wide."""
    return _in_group(user, GROUP_SYSTEM_STAFF)


def can_access_system_users(user) -> bool:
    """
    Check if user can access the MOE Staff (System Users) UI.

    Only system-level users should see/access MOE Staff:
    - Superusers: always
    - Admins: always (system-wide full access)
    - System Admins: always
    - System Staff: always (read-only system-wide)

    School-level groups should NOT access MOE Staff:
    - School Admins: no access
    - School Staff: no access
    - Teachers: no access
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    # Admins and System-level groups can access
    if is_admin(user) or is_system_staff(user):
        return True

    return False


def is_admins_group(user) -> bool:
    """
    Check if user is in the 'Admins' group specifically.

    Used for features that should only be accessible to the Admins group,
    like the Pending Users management.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_group(user, GROUP_ADMINS)


def has_app_access(user) -> bool:
    """
    Check if user has any role that grants access to the application.
    Requires either SchoolStaff or SystemUser profile + a group membership.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    # Check if user has a profile (SchoolStaff or SystemUser)
    has_profile = hasattr(user, 'school_staff') or hasattr(user, 'system_user')
    if not has_profile:
        return False

    # Check if user is in any group
    return user.groups.exists()


# Legacy function names for backward compatibility
def is_inclusive_admin(user) -> bool:
    """Deprecated: Use is_admin() instead."""
    return is_admin(user)


def is_inclusive_staff(user) -> bool:
    """Deprecated: Use is_school_staff() instead."""
    return is_school_staff(user)


def is_inclusive_school_admin(user) -> bool:
    """Deprecated: Use is_school_admin() instead."""
    return is_school_admin(user)


def is_inclusive_teacher(user) -> bool:
    """Deprecated: Use is_teacher() instead."""
    return is_teacher(user)


# ---- User ↔ School helpers --------------------------------------------------


def get_user_schools(user):
    """
    Return the EmisSchool queryset for which the user has an *active*
    SchoolStaffAssignment.

    Active == assignment.end_date is NULL (no end date).
    Teachers and SchoolStaff both use this; Admins/superusers don't need it
    for permissions, but we might still use it for defaults later.
    """
    if not user or not user.is_authenticated:
        return EmisSchool.objects.none()

    # Check if user has SchoolStaff profile
    if not hasattr(user, 'school_staff'):
        return EmisSchool.objects.none()

    # SchoolStaffAssignment uses:
    #   school_staff -> SchoolStaff
    #   school_staff.user -> AUTH_USER
    #   school -> EmisSchool (related_name="staff_assignments")
    #   end_date (nullable)
    return EmisSchool.objects.filter(
        staff_assignments__school_staff__user=user,
        staff_assignments__end_date__isnull=True,
    ).distinct()


# ---- SchoolStaff-specific permissions --------------------------------------


def can_view_staff(user, staff) -> bool:
    """
    Who can *view* a staff member?

    - Admins/superusers: always.
    - School Admins: only if they share at least one active school membership.
    - Teachers: only if they share at least one active school membership.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_admin(user):
        return True
    if is_school_admin(user) or is_teacher(user):
        return user_has_school_access_to_staff(user, staff)
    return False


def user_has_school_access_to_staff(user, staff) -> bool:
    """
    Row-level rule: does this user have school-based access to this staff member?

    - Admins/superusers: always True.
    - Teachers/School Admins: only if there is at least one intersection between
      their active schools and the staff member's active schools.
    - Others: False.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or is_admin(user):
        return True

    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return False

    staff_schools = get_user_schools(staff.user)
    if not staff_schools.exists():
        return False

    return staff_schools.filter(pk__in=user_schools.values("pk")).exists()


def filter_staff_for_user(qs: QuerySet, user) -> QuerySet:
    """
    Apply row-level access rules to a SchoolStaff queryset *for the list view*.

    - Superusers / Admins: see all staff in qs.
    - School Admins: only see staff with whom they share at least
      one active school membership.
    - Teachers: only see staff with whom they share at least
      one active school membership.
    - Everyone else: see nothing.
    """
    if not user or not user.is_authenticated:
        return qs.none()

    # Admins/superusers: no restriction
    if user.is_superuser or is_admin(user):
        return qs

    # Only School Admins and Teachers get per-school restricted views
    if not (is_school_admin(user) or is_teacher(user)):
        return qs.none()

    # Get the user's active schools
    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return qs.none()

    # Filter staff who have active memberships in any of the user's schools
    allowed_school_nos = list(user_schools.values_list("emis_school_no", flat=True))

    if not allowed_school_nos:
        return qs.none()

    # Filter by staff who have memberships at schools the user has access to
    # Using the annotated latest_school_no field from the view
    return qs.filter(latest_school_no__in=allowed_school_nos)


def can_create_staff_membership(user, target_school=None) -> bool:
    """
    Who can *create* a staff school membership?

    - Admins/superusers: always (any school).
    - School Admins: only for their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        target_school: Optional EmisSchool instance to validate school-scoped access
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can create memberships for any school
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only create memberships for schools they have access to
    if is_school_admin(user):
        if target_school is None:
            # Permission check without specific school - allow attempt
            # (school validation happens later in the view/form)
            return True
        # Validate that the target school is one of the user's active schools
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=target_school.pk).exists()

    return False


def can_edit_staff_membership(user, membership) -> bool:
    """
    Who can *edit* a staff school membership?

    - Admins/superusers: always.
    - School Admins: only if the membership is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        membership: SchoolStaffAssignment instance to edit
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can edit any membership
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only edit memberships for their schools
    if is_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=membership.school.pk).exists()

    return False


def can_delete_staff_membership(user, membership) -> bool:
    """
    Who can *delete* a staff school membership?

    - Admins/superusers: always.
    - School Admins: only if the membership is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        membership: SchoolStaffAssignment instance to delete
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can delete any membership
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only delete memberships for their schools
    if is_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=membership.school.pk).exists()

    return False


# ============================================================================
# SchoolStaff Edit Permissions
# ============================================================================


def can_edit_staff(user, staff) -> bool:
    """
    Who can *edit* a school staff member's profile (staff_type, groups)?

    - Superusers: always.
    - Admins group: always.
    - System Admins group: always (system-wide access).
    - School Admins group: only if they share at least one active school membership.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    if _in_group(user, GROUP_SYSTEM_ADMINS):
        return True
    if is_school_admin(user):
        return user_has_school_access_to_staff(user, staff)
    return False


def can_edit_staff_groups(user, staff) -> bool:
    """
    Who can *change group memberships* for a school staff member?

    - Superusers: always (can assign any group including Admins).
    - Admins group: always (can assign any group including Admins).
    - System Admins group: yes, but cannot assign the Admins group.
    - School Admins group: yes (for staff they have school access to),
      but cannot assign the Admins group.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    if _in_group(user, GROUP_SYSTEM_ADMINS):
        return True
    if is_school_admin(user):
        return user_has_school_access_to_staff(user, staff)
    return False


# ============================================================================
# SystemUser Edit Permissions
# ============================================================================


def can_edit_system_user(user, system_user) -> bool:
    """
    Who can *edit* a system user's profile (organization, position, groups)?

    - Superusers: always.
    - Admins group: always.
    - System Admins group: yes (but with group restrictions).
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    if _in_group(user, GROUP_SYSTEM_ADMINS):
        return True
    return False


def can_edit_system_user_groups(user, system_user) -> bool:
    """
    Who can *change group memberships* for a system user?

    - Superusers: always (can assign any group including Admins).
    - Admins group: always (can assign any group including Admins).
    - System Admins group: yes, but cannot assign the Admins group.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    if _in_group(user, GROUP_SYSTEM_ADMINS):
        return True
    return False


# ============================================================================
# Pending Users Permissions
# ============================================================================


def can_manage_pending_users(user) -> bool:
    """
    Who can manage pending users (view list, assign roles, delete)?

    - Superusers: always.
    - Admins group: always.
    - System Admins group: yes.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    if _in_group(user, GROUP_SYSTEM_ADMINS):
        return True
    return False


def can_assign_admins_group(user) -> bool:
    """
    Who can assign the 'Admins' group to users?

    - Superusers: always.
    - Admins group: yes.
    - System Admins group: NO (they cannot elevate to Admins).
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_admins_group(user):
        return True
    return False
