"""
Views for core models.

This module provides views for managing:
- Dashboard: Overview of all core models with KPIs and recent activity
- SystemUser: System-level users (MOE staff, consultants, administrators)
- SchoolStaff: School-level staff and their school assignments
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch, OuterRef, Subquery
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.text import capfirst

from core.models import SystemUser, SchoolStaff, SchoolStaffAssignment
from core.decorators import require_app_access
from core.forms import (
    SchoolStaffAssignmentForm,
    SchoolStaffEditForm,
    AssignSchoolStaffForm,
    AssignSystemUserForm,
    SystemUserEditForm,
)
from core.permissions import (
    filter_staff_for_user,
    can_view_staff,
    can_edit_staff,
    can_edit_staff_groups,
    can_create_staff_membership,
    can_edit_staff_membership,
    can_delete_staff_membership,
    can_access_system_users,
    can_edit_system_user,
    can_edit_system_user_groups,
    can_manage_pending_users,
    is_admins_group,
    is_school_admin,
    GROUP_ADMINS,
    GROUP_SCHOOL_STAFF,
    GROUP_TEACHERS,
    GROUP_SYSTEM_ADMINS,
    _in_group,
)
from integrations.models import EmisSchool

User = get_user_model()


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]


def _summarize_permissions(perms_queryset):
    """
    Group permissions into action buckets (view/add/change/delete/other)
    and return a list of sections ready for templates, e.g.:

    [
      {"key": "view", "label": "View", "models": ["Staff", "School"]},
      {"key": "add", "label": "Add", "models": ["System User", "School Staff"]},
      ...
    ]
    """
    buckets = {
        "view": set(),
        "add": set(),
        "change": set(),
        "delete": set(),
        "other": set(),
    }

    # Preload content_type for efficiency
    perms = perms_queryset.select_related("content_type")

    for p in perms:
        codename = p.codename

        # Standard Django model perms: view/add/change/delete_*
        action_key = "other"
        for action in ("view", "add", "change", "delete"):
            if codename.startswith(f"{action}_"):
                action_key = action
                break

        # Use the model's verbose_name when available
        model_class = p.content_type.model_class()
        if model_class is not None:
            model_label = capfirst(model_class._meta.verbose_name)
        else:
            model_label = capfirst(p.content_type.model.replace("_", " "))

        buckets[action_key].add(model_label)

    labels = {
        "view": "View",
        "add": "Add",
        "change": "Change",
        "delete": "Delete",
        "other": "Other",
    }

    sections = []
    for key in ("view", "add", "change", "delete", "other"):
        models = sorted(buckets[key])
        if models:
            sections.append(
                {
                    "key": key,
                    "label": labels[key],
                    "models": models,
                }
            )
    return sections


@login_required
@require_app_access
def dashboard(request):
    """
    Main dashboard showing overview of all core models.

    Displays:
    - SchoolStaff KPIs (total, recent additions, unassigned, by role)
    - Schools KPIs (active schools)
    - Recent activity feed across all core models
    """
    # Time window for "recent" counts (e.g. last 30 days)
    now = timezone.now()
    start_period = now - timedelta(days=30)

    # --- SchoolStaff KPIs ---
    total_staff = SchoolStaff.objects.count()
    staff_added_recent = SchoolStaff.objects.filter(created_at__gte=start_period).count()

    # SchoolStaff with no assignments (unassigned to any school)
    staff_unassigned = SchoolStaff.objects.filter(assignments__isnull=True).distinct().count()

    # Users by groups (count ALL users in these groups, not just SchoolStaff)
    admin_count = User.objects.filter(groups__name=GROUP_ADMINS).distinct().count()
    staff_teacher_count = (
        SchoolStaff.objects.filter(user__groups__name=GROUP_TEACHERS)
        .distinct()
        .count()
    )

    # --- SystemUser (MOE Staff) KPIs ---
    total_system_users = SystemUser.objects.count()
    system_users_added_recent = SystemUser.objects.filter(created_at__gte=start_period).count()

    # --- Schools KPIs ---
    active_schools = EmisSchool.objects.filter(active=True).count()

    # --- Pending Registrations KPIs ---
    from teacher_registration.models import TeacherRegistration

    pending_reg_draft = TeacherRegistration.objects.filter(
        status=TeacherRegistration.DRAFT
    ).count()
    pending_reg_submitted = TeacherRegistration.objects.filter(
        status=TeacherRegistration.SUBMITTED
    ).count()
    pending_reg_under_review = TeacherRegistration.objects.filter(
        status=TeacherRegistration.UNDER_REVIEW
    ).count()
    pending_reg_rejected = TeacherRegistration.objects.filter(
        status=TeacherRegistration.REJECTED
    ).count()
    pending_reg_total = (
        pending_reg_draft + pending_reg_submitted + pending_reg_under_review + pending_reg_rejected
    )

    # --- Recent activity (simple unified event log across core models) ---
    events = []

    def add_events_from_queryset(qs, entity_label, detail_url_name=None):
        for obj in qs:
            when = getattr(obj, "last_updated_at", None) or getattr(
                obj, "created_at", None
            )
            created_at = getattr(obj, "created_at", None)
            last_updated_at = getattr(obj, "last_updated_at", None)

            if created_at and last_updated_at and last_updated_at > created_at:
                action = "Updated"
            elif created_at:
                action = "Created"
            else:
                action = "Activity"

            by_user = getattr(obj, "last_updated_by", None) or getattr(
                obj, "created_by", None
            )
            # Display full name, fallback to email, then username
            by_display = None
            if by_user:
                full_name = by_user.get_full_name()
                if full_name:
                    by_display = full_name
                elif by_user.email:
                    by_display = by_user.email
                else:
                    by_display = by_user.username

            url = None
            if detail_url_name and when:
                try:
                    url = reverse(detail_url_name, args=[obj.pk])
                except Exception:
                    url = None

            if when:
                events.append(
                    {
                        "when": when,
                        "entity": entity_label,
                        "action": action,
                        "by": by_display,
                        "url": url,
                    }
                )

    # Pull a few recent records from each core model
    add_events_from_queryset(
        SchoolStaff.objects.order_by("-last_updated_at")[:5],
        "SchoolStaff",
        detail_url_name="core:staff_detail",
    )
    add_events_from_queryset(
        SchoolStaffAssignment.objects.order_by("-last_updated_at")[:5],
        "SchoolStaff assignment",
        detail_url_name=None,
    )

    # Sort all events by time and keep the latest 10
    events = sorted(events, key=lambda e: e["when"], reverse=True)[:10]

    context = {
        "active": "dashboard",
        # User KPIs
        "admin_count": admin_count,
        "staff_teacher_count": staff_teacher_count,
        # SystemUser (MOE Staff) KPIs
        "total_system_users": total_system_users,
        "system_users_added_recent": system_users_added_recent,
        # Schools KPIs
        "active_schools": active_schools,
        # Pending Registrations KPIs
        "pending_reg_total": pending_reg_total,
        "pending_reg_draft": pending_reg_draft,
        "pending_reg_submitted": pending_reg_submitted,
        "pending_reg_under_review": pending_reg_under_review,
        "pending_reg_rejected": pending_reg_rejected,
        # Activity
        "recent_events": events,
    }
    return render(request, "dashboard.html", context)


def _page_window(page_obj, radius=2, edges=2):
    """
    Build a compact pagination window like:
    1 2 & 8 9 10 11 12 & 29 30
    Returns a list of ints and '&' strings.
    """
    total = page_obj.paginator.num_pages
    current = page_obj.number
    pages = set()

    # edges
    for p in range(1, min(edges, total) + 1):
        pages.add(p)
    for p in range(max(1, total - edges + 1), total + 1):
        pages.add(p)

    # window around current
    for p in range(current - radius, current + radius + 1):
        if 1 <= p <= total:
            pages.add(p)

    pages = sorted(pages)
    window = []
    prev = 0
    for p in pages:
        if prev and p != prev + 1:
            window.append("&")
        window.append(p)
        prev = p
    return window


@login_required
@require_app_access
def system_user_list(request):
    """
    List all system users with search, filtering, and sorting capabilities.

    Only accessible by system-level users (Admins, System Admins, System Staff).
    School-level users (School Admins, School Staff, Teachers) cannot access this view.

    Query parameters:
        q: Search by name
        email: Filter by email
        organization: Filter by organization
        sort: Sort field (name, email, organization)
        dir: Sort direction (asc/desc)
        per_page: Number of results per page
        page: Current page number
    """
    # Check if user can access MOE Staff UI
    if not can_access_system_users(request.user):
        return render(request, "accounts/forbidden.html", status=403)

    q = (request.GET.get("q") or "").strip()

    # Filters
    email_filter = (request.GET.get("email") or "").strip()
    organization_filter = (request.GET.get("organization") or "").strip()

    # Sorting
    sort = (request.GET.get("sort") or "").strip().lower()
    dir_ = (request.GET.get("dir") or "asc").strip().lower()
    dir_ = "desc" if dir_ == "desc" else "asc"  # sanitize

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Base queryset
    system_users_qs = SystemUser.objects.select_related("user")

    # Search by name
    if q:
        system_users_qs = system_users_qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )

    # Search by email
    if email_filter:
        system_users_qs = system_users_qs.filter(user__email__icontains=email_filter)

    # Filter by organization
    if organization_filter:
        system_users_qs = system_users_qs.filter(organization__icontains=organization_filter)

    # Sorting map
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "email": ("user__email", "user__last_name", "user__first_name"),
        "organization": ("organization", "user__last_name", "user__first_name"),
    }

    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        system_users_qs = system_users_qs.order_by(*order_fields)
    else:
        # Default ordering by name
        system_users_qs = system_users_qs.order_by("user__last_name", "user__first_name")

    # Pagination
    paginator = Paginator(system_users_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Check if user can edit any system user (for showing Edit buttons)
    # This is a simple check - user must be superuser, Admins, or System Admins
    user_can_edit = (
        request.user.is_superuser
        or request.user.groups.filter(name__in=["Admins", "System Admins"]).exists()
    )

    return render(
        request,
        "core/system_user_list.html",
        {
            "active": "system_users",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            # filters
            "email": email_filter,
            "organization": organization_filter,
            # sorting
            "sort": sort,
            "dir": dir_,
            # permissions
            "user_can_edit": user_can_edit,
        },
    )


@login_required
@require_app_access
def system_user_detail(request, pk):
    """
    Display detailed information for a single system user.

    Only accessible by system-level users (Admins, System Admins, System Staff).
    School-level users (School Admins, School Staff, Teachers) cannot access this view.

    Shows:
    - User account details
    - Organization and position
    - Groups and permissions
    - Audit information
    """
    # Check if user can access MOE Staff UI
    if not can_access_system_users(request.user):
        return render(request, "accounts/forbidden.html", status=403)

    system_user = get_object_or_404(
        SystemUser.objects.select_related("user", "created_by", "last_updated_by").prefetch_related(
            "user__groups__permissions",
            "user__user_permissions",
        ),
        pk=pk,
    )

    user_obj = system_user.user

    groups = (
        user_obj.groups.all()
        .prefetch_related("permissions__content_type")
        .order_by("name")
    )

    group_permissions = []
    for g in groups:
        group_permissions.append(
            {
                "group": g,
                "sections": _summarize_permissions(g.permissions.all()),
            }
        )

    direct_permission_sections = _summarize_permissions(
        user_obj.user_permissions.all().select_related("content_type")
    )

    context = {
        "system_user": system_user,
        "active": "system_users",
        "group_permissions": group_permissions,
        "direct_permission_sections": direct_permission_sections,
        "can_edit": can_edit_system_user(request.user, system_user),
    }
    return render(request, "core/system_user_detail.html", context)


@login_required
@require_app_access
def system_user_edit(request, pk):
    """
    Edit a system user's organization, position, and group memberships.

    Permissions:
    - Django Super Users: full access (all fields including groups)
    - Admins group: full access (all fields including groups)
    - System Admins group: can edit organization/position, and can edit groups
      but cannot assign the Admins group.
    - System Staff group: read-only, no edit access
    """
    # Check system-level access first
    if not can_access_system_users(request.user):
        raise PermissionDenied

    system_user = get_object_or_404(
        SystemUser.objects.select_related("user", "created_by", "last_updated_by"),
        pk=pk,
    )

    # Check edit permission
    if not can_edit_system_user(request.user, system_user):
        messages.error(request, "You do not have permission to edit this system user.")
        return redirect("core:system_user_detail", pk=pk)

    # Determine if user can edit groups
    can_edit_groups = can_edit_system_user_groups(request.user, system_user)

    if request.method == "POST":
        form = SystemUserEditForm(
            request.POST,
            user=request.user,
            system_user=system_user,
        )
        if form.is_valid():
            # Update SystemUser fields
            system_user.organization = form.cleaned_data["organization"]
            system_user.position_title = form.cleaned_data["position_title"]
            system_user.last_updated_by = request.user
            system_user.save()

            # Update groups only if user has permission
            if can_edit_groups:
                new_groups = form.cleaned_data["groups"]
                # Only update system-level groups, preserve any other groups
                system_groups = ["Admins", "System Admins", "System Staff"]
                # Remove old system-level groups
                system_user.user.groups.remove(
                    *system_user.user.groups.filter(name__in=system_groups)
                )
                # Add new groups
                system_user.user.groups.add(*new_groups)

            messages.success(
                request,
                f"System user {system_user.user.get_full_name() or system_user.user.username} updated successfully.",
            )
            return redirect("core:system_user_detail", pk=pk)
    else:
        form = SystemUserEditForm(
            user=request.user,
            system_user=system_user,
        )

    context = {
        "system_user": system_user,
        "form": form,
        "can_edit_groups": can_edit_groups,
        "active": "system_users",
    }
    return render(request, "core/system_user_edit.html", context)


# Note: SPECIAL_PERMISSIONS dictionary removed - no longer needed
# Access control is now based on profile (SchoolStaff/SystemUser) + group membership


@login_required
@require_app_access
def staff_list(request):
    q = (request.GET.get("q") or "").strip()

    # Filters
    school_filter = (
        request.GET.get("school") or ""
    ).strip()  # EmisSchool.emis_school_no
    email_filter = (request.GET.get("email") or "").strip()

    # Sorting
    sort = (request.GET.get("sort") or "").strip().lower()
    dir_ = (request.GET.get("dir") or "asc").strip().lower()
    dir_ = "desc" if dir_ == "desc" else "asc"  # sanitize

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Picklists (active only; adjust if you want all)
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_name")

    # ---- Latest assignment subqueries (for "current appointment" + filtering/sorting helper)
    assignment_qs = SchoolStaffAssignment.objects.filter(school_staff=OuterRef("pk")).order_by(
        "-id"
    )  # most recently created assignment; simple + robust

    latest_school_no = Subquery(assignment_qs.values("school__emis_school_no")[:1])
    latest_school_name = Subquery(assignment_qs.values("school__emis_school_name")[:1])

    staff_qs = (
        SchoolStaff.objects.select_related("user")
        .annotate(
            latest_school_no=latest_school_no,
            latest_school_name=latest_school_name,
        )
        .prefetch_related(
            Prefetch(
                "assignments",
                queryset=SchoolStaffAssignment.objects.select_related(
                    "school", "job_title"
                ),
            ),
            "user__groups",
        )
    )

    # Search by name
    if q:
        staff_qs = staff_qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )

    # Search by email
    if email_filter:
        staff_qs = staff_qs.filter(user__email__icontains=email_filter)

    # Filter by school (any assignment at that school)
    if school_filter:
        staff_qs = staff_qs.filter(
            assignments__school__emis_school_no=school_filter
        ).distinct()

    # Apply row-level permissions
    staff_qs = filter_staff_for_user(staff_qs, request.user)

    # Sorting map: align with table columns: Name, Email, Current Appointment
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "email": ("user__email", "user__last_name", "user__first_name"),
        "appointment": (
            "latest_school_name",
            "latest_school_no",
            "user__last_name",
            "user__first_name",
        ),
    }

    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        staff_qs = staff_qs.order_by(*order_fields)
    else:
        # Default ordering by name
        staff_qs = staff_qs.order_by("user__last_name", "user__first_name")

    # Pagination
    paginator = Paginator(staff_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Check if user can edit staff (for showing Edit buttons)
    # Superusers, Admins, System Admins, and School Admins can edit
    user_can_edit = (
        request.user.is_superuser
        or is_admins_group(request.user)
        or _in_group(request.user, GROUP_SYSTEM_ADMINS)
        or is_school_admin(request.user)
    )

    # Check if user can delete staff (for showing Delete buttons)
    # Only Admins and System Admins can delete
    user_can_delete = can_manage_pending_users(request.user)

    return render(
        request,
        "core/staff_list.html",
        {
            "active": "school_staff",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            # filters + lists
            "school": school_filter,
            "email": email_filter,
            "schools": schools,
            # sorting
            "sort": sort,
            "dir": dir_,
            # permissions
            "user_can_edit": user_can_edit,
            "user_can_delete": user_can_delete,
        },
    )


@login_required
@require_app_access
def staff_detail(request, pk):
    staff = get_object_or_404(
        SchoolStaff.objects.select_related("user").prefetch_related(
            "assignments__school",
            "assignments__job_title",
            "assignments__created_by",
            "assignments__last_updated_by",
            "user__groups__permissions",
            "user__user_permissions",
        ),
        pk=pk,
    )

    # Permission: can this user view this staff member?
    if not can_view_staff(request.user, staff):
        messages.error(request, "You do not have permission to view this staff member.")
        return redirect("core:staff_list")

    # Permission: who can add memberships?
    can_add_membership = can_create_staff_membership(request.user)

    membership_form = (
        SchoolStaffAssignmentForm(request.POST or None, user=request.user)
        if can_add_membership
        else None
    )

    if request.method == "POST":
        if not can_create_staff_membership(request.user):
            messages.error(
                request, "You do not have permission to add school memberships."
            )
        elif membership_form.is_valid():
            obj = membership_form.save(commit=False)
            obj.school_staff = staff

            # Additional validation: School Admins can only create memberships for their schools
            if not can_create_staff_membership(request.user, obj.school):
                messages.error(
                    request,
                    f"You do not have permission to create memberships for {obj.school.emis_school_name}.",
                )
            else:
                # audit fields (if defined on the model)
                if hasattr(obj, "created_by_id") and obj.created_by_id is None:
                    obj.created_by = request.user
                if hasattr(obj, "last_updated_by_id") and obj.last_updated_by_id is None:
                    obj.last_updated_by = request.user

                obj.save()
                messages.success(request, "School assignment added.")
                return redirect("core:staff_detail", pk=staff.pk)

    user_obj = staff.user

    groups = (
        user_obj.groups.all()
        .prefetch_related("permissions__content_type")
        .order_by("name")
    )

    group_permissions = []
    for g in groups:
        group_permissions.append(
            {
                "group": g,
                "sections": _summarize_permissions(g.permissions.all()),
            }
        )

    direct_permission_sections = _summarize_permissions(
        user_obj.user_permissions.all().select_related("content_type")
    )

    # Build per-assignment edit/delete permissions for template
    assignment_permissions = {}
    for assignment in staff.assignments.all():
        assignment_permissions[assignment.pk] = {
            "can_edit": can_edit_staff_membership(request.user, assignment),
            "can_delete": can_delete_staff_membership(request.user, assignment),
        }

    context = {
        "staff": staff,
        "active": "school_staff",
        "membership_form": membership_form,
        "can_add_membership": can_add_membership,
        "assignment_permissions": assignment_permissions,
        "group_permissions": group_permissions,
        "direct_permission_sections": direct_permission_sections,
        "can_edit": can_edit_staff(request.user, staff),
        "can_delete": can_manage_pending_users(request.user) and staff.user != request.user,
    }
    return render(request, "core/staff_detail.html", context)


@login_required
@require_app_access
def staff_edit(request, pk):
    """
    Edit a school staff member's staff_type and group memberships.

    Permissions:
    - Django Super Users: full access (all fields including groups)
    - Admins group: full access (all fields including groups)
    - System Admins group: can edit all fields including groups,
      but cannot assign the Admins group.
    - School Admins group: can edit staff_type and groups for staff at their schools,
      but cannot assign the Admins group.
    """
    staff = get_object_or_404(
        SchoolStaff.objects.select_related("user", "created_by", "last_updated_by"),
        pk=pk,
    )

    # Check edit permission
    if not can_edit_staff(request.user, staff):
        messages.error(request, "You do not have permission to edit this staff member.")
        return redirect("core:staff_detail", pk=pk)

    # Determine if user can edit groups
    can_edit_groups = can_edit_staff_groups(request.user, staff)

    if request.method == "POST":
        form = SchoolStaffEditForm(
            request.POST,
            user=request.user,
            school_staff=staff,
        )
        if form.is_valid():
            # Update SchoolStaff fields
            staff.staff_type = form.cleaned_data["staff_type"]
            staff.last_updated_by = request.user
            staff.save()

            # Update groups only if user has permission
            if can_edit_groups:
                new_groups = form.cleaned_data["groups"]
                # Only update school-level groups, preserve any other groups
                school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
                # Remove old school-level groups
                staff.user.groups.remove(
                    *staff.user.groups.filter(name__in=school_groups)
                )
                # Add new groups
                staff.user.groups.add(*new_groups)

            messages.success(
                request,
                f"Staff member {staff.user.get_full_name() or staff.user.username} updated successfully.",
            )
            return redirect("core:staff_detail", pk=pk)
    else:
        form = SchoolStaffEditForm(
            user=request.user,
            school_staff=staff,
        )

    context = {
        "staff": staff,
        "form": form,
        "can_edit_groups": can_edit_groups,
        "active": "school_staff",
    }
    return render(request, "core/staff_edit.html", context)


@login_required
@require_app_access
def staff_membership_edit(request, staff_id, pk):
    """
    Edit an existing SchoolStaffAssignment for a given staff member.
    """
    staff = get_object_or_404(SchoolStaff, pk=staff_id)
    membership = get_object_or_404(
        SchoolStaffAssignment,
        pk=pk,
        school_staff=staff,
    )

    # Permission: check if user can edit this specific membership
    if not can_edit_staff_membership(request.user, membership):
        messages.error(
            request, "You do not have permission to edit this school membership."
        )
        return redirect("core:staff_detail", pk=staff.pk)

    if request.method == "POST":
        form = SchoolStaffAssignmentForm(
            request.POST, instance=membership, user=request.user
        )
        if form.is_valid():
            obj = form.save(commit=False)

            # Additional validation: ensure school hasn't changed to one outside user's scope
            if not can_create_staff_membership(request.user, obj.school):
                messages.error(
                    request,
                    f"You do not have permission to assign memberships for {obj.school.emis_school_name}.",
                )
            else:
                # Audit: stamp last_updated_by if field exists
                if hasattr(obj, "last_updated_by_id"):
                    obj.last_updated_by = request.user

                obj.save()
                messages.success(request, "School assignment updated.")
                return redirect("core:staff_detail", pk=staff.pk)
    else:
        form = SchoolStaffAssignmentForm(instance=membership, user=request.user)

    context = {
        "active": "school_staff",
        "staff": staff,
        "membership": membership,
        "form": form,
    }
    return render(request, "core/staff_membership_edit.html", context)


@login_required
@require_app_access
def staff_membership_delete(request, staff_id, pk):
    """
    Confirm and delete a SchoolStaffAssignment for a given staff member.
    """
    staff = get_object_or_404(SchoolStaff, pk=staff_id)
    membership = get_object_or_404(
        SchoolStaffAssignment,
        pk=pk,
        school_staff=staff,
    )

    # Permission: check if user can delete this specific membership
    if not can_delete_staff_membership(request.user, membership):
        messages.error(
            request, "You do not have permission to delete this school membership."
        )
        return redirect("core:staff_detail", pk=staff.pk)

    if request.method == "POST":
        membership.delete()
        messages.success(request, "School assignment deleted.")
        return redirect("core:staff_detail", pk=staff.pk)

    context = {
        "active": "school_staff",
        "staff": staff,
        "membership": membership,
    }
    return render(request, "core/staff_membership_confirm_delete.html", context)


# ============================================================================
# Pending Users (User Role Assignment)
# ============================================================================


@login_required
@require_app_access
def pending_users_list(request):
    """
    List users who have signed in (via Google OAuth) but don't yet have
    a SchoolStaff or SystemUser profile assigned.

    Excludes users who have an active teacher registration (draft/submitted/under_review),
    as those are tracked in Pending Registrations instead.

    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Get user IDs with active registrations (these are tracked in Pending Registrations)
    from teacher_registration.models import TeacherRegistration

    users_with_active_registration = TeacherRegistration.objects.filter(
        status__in=[
            TeacherRegistration.DRAFT,
            TeacherRegistration.SUBMITTED,
            TeacherRegistration.UNDER_REVIEW,
            TeacherRegistration.REJECTED,
        ]
    ).values_list("user_id", flat=True)

    # Users without either profile (exclude superusers - they have full access already)
    # Also exclude users with active registrations
    pending_users_qs = User.objects.filter(
        school_staff__isnull=True,
        system_user__isnull=True,
        is_superuser=False,
    ).exclude(
        id__in=users_with_active_registration
    ).order_by("-date_joined")

    # Search by name or email
    if q:
        pending_users_qs = pending_users_qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(username__icontains=q)
        )

    # Pagination
    paginator = Paginator(pending_users_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/pending_users_list.html",
        {
            "active": "pending_users",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
        },
    )


@login_required
@require_app_access
def assign_school_staff(request, user_id):
    """
    Assign a pending user as School Staff.

    Creates a SchoolStaff profile and assigns them to selected groups.
    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Check if user already has a SchoolStaff profile
    if hasattr(target_user, "school_staff"):
        messages.warning(request, f"{target_user} already has a School Staff profile.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        form = AssignSchoolStaffForm(request.POST, user=request.user)
        if form.is_valid():
            # Create SchoolStaff profile
            staff = SchoolStaff.objects.create(
                user=target_user,
                staff_type=form.cleaned_data["staff_type"],
                created_by=request.user,
                last_updated_by=request.user,
            )

            # Assign groups
            groups = form.cleaned_data["groups"]
            target_user.groups.add(*groups)

            messages.success(
                request,
                f"{target_user.get_full_name() or target_user.username} has been assigned as School Staff.",
            )
            return redirect("core:staff_detail", pk=staff.pk)
    else:
        form = AssignSchoolStaffForm(user=request.user)

    return render(
        request,
        "core/assign_school_staff.html",
        {
            "active": "pending_users",
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
@require_app_access
def assign_system_user(request, user_id):
    """
    Assign a pending user as a System User.

    Creates a SystemUser profile and assigns them to selected groups.
    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Check if user already has a SystemUser profile
    if hasattr(target_user, "system_user"):
        messages.warning(request, f"{target_user} already has a System User profile.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        form = AssignSystemUserForm(request.POST, user=request.user)
        if form.is_valid():
            # Create SystemUser profile
            system_user = SystemUser.objects.create(
                user=target_user,
                organization=form.cleaned_data.get("organization", ""),
                position_title=form.cleaned_data.get("position_title", ""),
                created_by=request.user,
                last_updated_by=request.user,
            )

            # Assign groups
            groups = form.cleaned_data["groups"]
            target_user.groups.add(*groups)

            messages.success(
                request,
                f"{target_user.get_full_name() or target_user.username} has been assigned as a System User.",
            )
            return redirect("core:system_user_detail", pk=system_user.pk)
    else:
        form = AssignSystemUserForm(user=request.user)

    return render(
        request,
        "core/assign_system_user.html",
        {
            "active": "pending_users",
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
@require_app_access
def delete_pending_user(request, user_id):
    """
    Delete a pending user who has not been assigned a role.

    Accessible to users in the Admins or System Admins groups.
    Only users without SchoolStaff or SystemUser profiles can be deleted.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Safety check: only allow deletion of users without profiles
    has_school_staff = hasattr(target_user, "school_staff") and target_user.school_staff is not None
    has_system_user = hasattr(target_user, "system_user") and target_user.system_user is not None

    if has_school_staff or has_system_user:
        messages.error(
            request,
            f"{target_user} already has a role assigned and cannot be deleted from here. "
            "Use the Django admin to manage this user.",
        )
        return redirect("core:pending_users_list")

    # Prevent deleting yourself
    if target_user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("core:pending_users_list")

    # Prevent deleting superusers
    if target_user.is_superuser:
        messages.error(request, "Superusers cannot be deleted from here. Use the Django admin.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        username = target_user.username
        full_name = target_user.get_full_name() or username
        target_user.delete()
        messages.success(request, f"User '{full_name}' has been deleted.")
        return redirect("core:pending_users_list")

    return render(
        request,
        "core/delete_pending_user.html",
        {
            "active": "pending_users",
            "target_user": target_user,
        },
    )


@login_required
@require_app_access
def staff_delete(request, pk):
    """
    Delete a School Staff record.

    Deletes the SchoolStaff profile (and related assignments/documents),
    leaving the Django User intact as a pending user.

    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    staff = get_object_or_404(SchoolStaff.objects.select_related("user"), pk=pk)

    # Prevent deleting yourself
    if staff.user == request.user:
        messages.error(request, "You cannot delete your own staff profile.")
        return redirect("core:staff_detail", pk=pk)

    if request.method == "POST":
        user = staff.user
        full_name = user.get_full_name() or user.username
        staff.delete()
        messages.success(
            request,
            f"Staff profile for '{full_name}' has been deleted. "
            f"The user account remains as a pending user.",
        )
        return redirect("core:staff_list")

    return render(
        request,
        "core/staff_delete.html",
        {
            "active": "school_staff",
            "staff": staff,
        },
    )
