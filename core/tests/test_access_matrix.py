"""
Access-control matrix: every URL in the project, requested with GET by every
role, must produce exactly the expected outcome.

This is the single strongest regression guard for a change to a decorator,
a permission predicate, or a view's guard clause. It also doubles as a page
smoke test: every page is rendered at least once by a role that is allowed
to see it, so a template error surfaces here.

Roles
-----
anonymous       not logged in
no_access       logged in, no profile, no group
applicant       logged in, no profile, owns the draft registration
superuser       Django superuser
admins          SchoolStaff profile + "Admins" group
system_admins   SystemUser profile + "System Admins" group
system_staff    SystemUser profile + "System Staff" group
school_admins   SchoolStaff profile + "School Admins" group (no shared school)
teachers        SchoolStaff profile + "Teachers" group (no shared school)
school_staff    SchoolStaff profile + "School Staff" group
"""

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

import pytest
from django.urls import reverse

from core import permissions as p
from core.models import SchoolStaff, StaffEducationRecord
from core.tests.factories import (
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    SystemUserFactory,
    UserFactory,
    add_to_groups,
    school_staff_user,
    system_user,
)
from integrations.tests.factories import EmisSubjectFactory, EmisTeacherQualFactory
from teacher_registration import constants
from teacher_registration.tests.factories import (
    ClaimedSchoolAppointmentFactory,
    RegistrationConditionFactory,
    RegistrationDocumentFactory,
    TeacherRegistrationFactory,
)

pytestmark = pytest.mark.django_db

ROLES = [
    "anonymous",
    "no_access",
    "applicant",
    "superuser",
    "admins",
    "system_admins",
    "system_staff",
    "school_admins",
    "teachers",
    "school_staff",
]
MANAGERS = {"superuser", "admins", "system_admins"}

LOGIN = "redirect-to-login"
NOPERM = "redirect-to-no-permissions"


@dataclass(frozen=True)
class KnownBug:
    """The outcome the view should produce, and the one it produces today."""

    correct: object
    actual: object
    reason: str


# ---------------------------------------------------------------------------
# Expectation builders
# ---------------------------------------------------------------------------


def _fill(base, **overrides):
    missing = set(ROLES) - set(base)
    assert not missing, f"missing roles: {missing}"
    base.update(overrides)
    return base


def public(ok=200, **overrides):
    return _fill({role: ok for role in ROLES}, **overrides)


def login_only(ok, **overrides):
    """@login_required only: anonymous goes to login, everyone else gets `ok`."""
    return _fill({role: (LOGIN if role == "anonymous" else ok) for role in ROLES}, **overrides)


def app_access(ok=200, **overrides):
    """@require_app_access: profile + group needed, no further restriction."""
    base = {role: ok for role in ROLES}
    base.update(anonymous=LOGIN, no_access=NOPERM, applicant=NOPERM)
    return _fill(base, **overrides)


def manage(ok=200, denied=403, **overrides):
    """can_manage_pending_users(): superuser, Admins, System Admins."""
    base = {role: (ok if role in MANAGERS else denied) for role in ROLES}
    base.update(anonymous=LOGIN, no_access=NOPERM, applicant=NOPERM)
    return _fill(base, **overrides)


def system_users(ok=200, **overrides):
    """can_access_system_users(): managers plus System Staff."""
    return manage(ok, **{"system_staff": ok, **overrides})


def admins_only(ok=200, **overrides):
    """is_admins_group(): superuser and Admins; System Admins are refused."""
    return manage(ok, **{"system_admins": 403, **overrides})


def owner_or_manager(owner_ok, manager_ok, **overrides):
    """Views guarded by `is_owner or can_manage_pending_users()` (no app-access decorator)."""
    base = {role: 403 for role in ROLES}
    base.update({role: manager_ok for role in MANAGERS})
    base.update(anonymous=LOGIN, applicant=owner_ok)
    return _fill(base, **overrides)


# ---------------------------------------------------------------------------
# World: the objects the URLs point at
# ---------------------------------------------------------------------------


@dataclass
class World:
    applicant: object
    draft: object
    appointment: object
    document: object
    under_review: object
    condition: object
    system_user_profile: object
    staff: object
    membership: object
    pending_user: object
    teacher: object
    education_record: object
    assignment: object


@pytest.fixture
def world(google_social_app):
    applicant = UserFactory(username="applicant@example.org")
    draft = TeacherRegistrationFactory(user=applicant)
    appointment = ClaimedSchoolAppointmentFactory(registration=draft)
    document = RegistrationDocumentFactory(registration=draft)
    under_review = TeacherRegistrationFactory(under_review=True)
    condition = RegistrationConditionFactory(registration=under_review)

    system_user_profile = SystemUserFactory()
    add_to_groups(system_user_profile.user, p.GROUP_SYSTEM_STAFF)
    staff = SchoolStaffFactory()
    membership = SchoolStaffAssignmentFactory(school_staff=staff)
    pending_user = UserFactory(username="pending@example.org")

    teacher = SchoolStaffFactory(
        staff_type=SchoolStaff.TEACHING_STAFF,
        national_id_number="T-001",
        teacher_registration_number="TR26-TEACH1-X",
        registration_application_status=constants.APPROVED,
        registration_granted_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
    )
    education_record = StaffEducationRecord.objects.create(
        school_staff=teacher,
        institution_name="Uni",
        qualification=EmisTeacherQualFactory(),
        major=EmisSubjectFactory(),
    )
    assignment = SchoolStaffAssignmentFactory(school_staff=teacher)
    return World(
        applicant, draft, appointment, document, under_review, condition,
        system_user_profile, staff, membership, pending_user, teacher,
        education_record, assignment,
    )


def build_user(role, world):
    if role == "anonymous":
        return None
    if role == "no_access":
        return UserFactory()
    if role == "applicant":
        return world.applicant
    if role == "superuser":
        return UserFactory(is_superuser=True, is_staff=True)
    if role == "admins":
        return school_staff_user(p.GROUP_ADMINS)
    if role == "system_admins":
        return system_user(p.GROUP_SYSTEM_ADMINS)
    if role == "system_staff":
        return system_user(p.GROUP_SYSTEM_STAFF)
    if role == "school_admins":
        return school_staff_user(p.GROUP_SCHOOL_ADMINS)
    if role == "teachers":
        return school_staff_user(p.GROUP_TEACHERS)
    if role == "school_staff":
        return school_staff_user(p.GROUP_SCHOOL_STAFF)
    raise ValueError(role)


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

# (url name, kwargs builder, expected outcome per role)
MATRIX = [
    # Root and accounts
    ("dashboard", None, app_access()),
    ("core:dashboard", None, app_access()),
    ("accounts:login", None, public(302, anonymous=200)),
    ("accounts:logout", None, login_only(302)),
    ("accounts:post_login_router", None, login_only(302)),
    ("accounts:no_permissions", None, login_only(200)),
    ("admin:index", None, public(302, superuser=200)),
    # core: system users
    ("core:system_user_list", None, system_users()),
    ("core:system_user_detail", lambda w: {"pk": w.system_user_profile.pk}, system_users()),
    ("core:system_user_edit", lambda w: {"pk": w.system_user_profile.pk}, system_users(system_staff=302)),
    # core: school staff
    ("core:staff_list", None, app_access()),
    ("core:staff_detail", lambda w: {"pk": w.staff.pk}, manage(denied=302)),
    ("core:staff_edit", lambda w: {"pk": w.staff.pk}, manage(denied=302)),
    ("core:staff_delete", lambda w: {"pk": w.staff.pk}, manage()),
    ("core:staff_membership_edit", lambda w: {"staff_id": w.staff.pk, "pk": w.membership.pk}, manage(denied=302)),
    ("core:staff_membership_delete", lambda w: {"staff_id": w.staff.pk, "pk": w.membership.pk}, manage(denied=302)),
    # core: pending users
    ("core:pending_users_list", None, manage()),
    ("core:assign_school_staff", lambda w: {"user_id": w.pending_user.pk}, manage()),
    ("core:assign_system_user", lambda w: {"user_id": w.pending_user.pk}, manage()),
    ("core:delete_pending_user", lambda w: {"user_id": w.pending_user.pk}, manage()),
    # core: utilities
    ("core:pdf_split", None, manage()),
    ("core:pdf_split_results", lambda w: {"job_id": "0" * 32}, manage(302)),
    ("core:pdf_split_download", lambda w: {"job_id": "0" * 32, "page_num": 1}, manage(302)),
    ("core:pdf_split_download_all", lambda w: {"job_id": "0" * 32}, manage(302)),
    ("core:pdf_merge", None, manage()),
    ("core:test_email", None, manage()),
    # core: reports and settings
    ("core:reports", None, app_access()),
    # 200 when WeasyPrint's native libraries are installed, otherwise a redirect
    # back to the reports index with an error message.
    ("core:report_teacher_summary", None, app_access((200, 302))),
    ("core:settings", None, manage()),
    ("core:sync_emis_lookups", None, manage(302)),
    ("core:settings_lookup_list", lambda w: {"slug": "schools"}, manage()),
    ("core:settings_lookup_update", lambda w: {"slug": "schools", "pk": "X"}, manage(405)),
    ("core:settings_condition_types", None, admins_only()),
    ("core:settings_condition_type_update", lambda w: {"pk": "X"}, admins_only(405)),
    # teacher_registration: public
    ("teacher_registration:public_landing", None, public()),
    ("teacher_registration:public_start", None, public(302)),
    ("teacher_registration:public_signout", None, public(302)),
    # teacher_registration: teacher-facing
    (
        "teacher_registration:my_registration",
        None,
        login_only(302, school_admins=200, teachers=200, school_staff=200),
    ),
    # Every authenticated user is redirected: to the dashboard if they already
    # have a staff profile, otherwise to a (new or existing) draft's edit page.
    ("teacher_registration:create", None, login_only(302)),
    ("teacher_registration:edit", lambda w: {"pk": w.draft.pk}, owner_or_manager(200, 200)),
    ("teacher_registration:submit", lambda w: {"pk": w.draft.pk}, owner_or_manager(200, 403)),
    ("teacher_registration:document_upload", lambda w: {"registration_pk": w.draft.pk}, owner_or_manager(302, 302)),
    (
        "teacher_registration:document_delete",
        lambda w: {"registration_pk": w.draft.pk, "pk": w.document.pk},
        owner_or_manager(302, 302),
    ),
    (
        "teacher_registration:manage_claimed_duties",
        lambda w: {"appointment_id": w.appointment.pk},
        owner_or_manager(200, 200),
    ),
    ("teacher_registration:registration_renew", None, login_only(302)),
    (
        "teacher_registration:staff_register_teacher",
        None,
        manage(no_access=403, applicant=403),
    ),
    # teacher_registration: review workflow
    ("teacher_registration:pending_list", None, manage()),
    ("teacher_registration:review", lambda w: {"pk": w.under_review.pk}, manage()),
    ("teacher_registration:toggle_ready", lambda w: {"pk": w.under_review.pk}, manage(405)),
    ("teacher_registration:condition_add", lambda w: {"pk": w.under_review.pk}, manage(405)),
    ("teacher_registration:condition_remove", lambda w: {"pk": w.condition.pk}, manage(405)),
    ("teacher_registration:registration_delete", lambda w: {"pk": w.under_review.pk}, manage()),
    ("teacher_registration:history", None, manage()),
    # teacher_registration: approved teachers
    ("teacher_registration:teachers_list", None, app_access()),
    ("teacher_registration:teacher_detail", lambda w: {"pk": w.teacher.pk}, app_access()),
    ("teacher_registration:teacher_delete", lambda w: {"pk": w.teacher.pk}, manage()),
    ("teacher_registration:teacher_photo_crop", lambda w: {"pk": w.teacher.pk}, manage(405)),
    ("teacher_registration:teacher_resend_renewal_notification", lambda w: {"pk": w.teacher.pk}, manage(302)),
    ("teacher_registration:teacher_force_expiry", lambda w: {"pk": w.teacher.pk}, manage(302)),
    ("teacher_registration:teacher_edit_granted_at", lambda w: {"pk": w.teacher.pk}, manage(302)),
    ("teacher_registration:teacher_edit_section", lambda w: {"pk": w.teacher.pk, "section": "professional"}, manage()),
    ("teacher_registration:teacher_record_add", lambda w: {"pk": w.teacher.pk, "rtype": "education"}, manage()),
    (
        "teacher_registration:teacher_record_edit",
        lambda w: {"pk": w.teacher.pk, "rtype": "education", "record_pk": w.education_record.pk},
        manage(),
    ),
    (
        "teacher_registration:teacher_record_delete",
        lambda w: {"pk": w.teacher.pk, "rtype": "education", "record_pk": w.education_record.pk},
        manage(),
    ),
    ("teacher_registration:teacher_assignment_add", lambda w: {"pk": w.teacher.pk}, manage()),
    (
        "teacher_registration:teacher_assignment_edit",
        lambda w: {"pk": w.teacher.pk, "assignment_pk": w.assignment.pk},
        manage(),
    ),
    ("teacher_registration:teacher_renew_on_behalf", lambda w: {"pk": w.teacher.pk}, manage(302)),
    ("teacher_registration:teacher_certificate", lambda w: {"pk": w.teacher.pk}, app_access()),
]


def _params():
    for url_name, kwargs_builder, expected in MATRIX:
        for role in ROLES:
            outcome = expected[role]
            marks = []
            if isinstance(outcome, KnownBug):
                marks.append(pytest.mark.xfail(strict=True, reason=outcome.reason))
                outcome = outcome.correct
            yield pytest.param(url_name, kwargs_builder, role, outcome, id=f"{url_name}[{role}]", marks=marks)


def _assert_outcome(response, outcome, url):
    if outcome == LOGIN:
        assert response.status_code == 302, f"{url}: expected login redirect, got {response.status_code}"
        assert response["Location"].startswith(reverse("account_login")), response["Location"]
    elif outcome == NOPERM:
        assert response.status_code == 302, f"{url}: expected no-permissions redirect, got {response.status_code}"
        assert response["Location"] == reverse("accounts:no_permissions"), response["Location"]
    elif isinstance(outcome, tuple):
        assert response.status_code in outcome, f"{url}: expected one of {outcome}, got {response.status_code}"
    else:
        assert response.status_code == outcome, f"{url}: expected {outcome}, got {response.status_code}"


@pytest.mark.parametrize(("url_name", "kwargs_builder", "role", "outcome"), list(_params()))
def test_get(client, world, url_name, kwargs_builder, role, outcome):
    user = build_user(role, world)
    if user is not None:
        client.force_login(user)
    url = reverse(url_name, kwargs=kwargs_builder(world) if kwargs_builder else None)
    response = client.get(url)
    _assert_outcome(response, outcome, url)


def test_matrix_covers_every_project_url():
    """A new URL must be added to the matrix, or this test fails."""
    from django.urls import get_resolver

    def walk(patterns, namespace=None):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                ns = pattern.namespace or namespace
                if ns and ns != namespace and namespace:
                    ns = f"{namespace}:{ns}"
                yield from walk(pattern.url_patterns, ns)
            elif pattern.name:
                yield f"{namespace}:{pattern.name}" if namespace else pattern.name

    project_names = {
        name
        for name in walk(get_resolver().url_patterns)
        if name.split(":")[0] in {"core", "teacher_registration", "accounts", "dashboard"}
    }
    covered = {row[0] for row in MATRIX}
    assert project_names <= covered, f"URLs missing from the matrix: {sorted(project_names - covered)}"


# ---------------------------------------------------------------------------
# A few outcomes that depend on the request rather than the role
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client_user(client):
    user = school_staff_user(p.GROUP_ADMINS)
    client.force_login(user)
    return user


def test_certificate_is_a_pdf(client, world, admin_client_user):
    response = client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": world.teacher.pk}))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_certificate_refused_for_unapproved_teacher(client, world, admin_client_user):
    world.teacher.registration_application_status = constants.DRAFT
    world.teacher.save()
    response = client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": world.teacher.pk}))
    assert response.status_code == 403


def test_unknown_lookup_slug_is_404(client, admin_client_user):
    assert client.get(reverse("core:settings_lookup_list", kwargs={"slug": "nope"})).status_code == 404


def test_unknown_profile_section_is_404(client, world, admin_client_user):
    url = reverse("teacher_registration:teacher_edit_section", kwargs={"pk": world.teacher.pk, "section": "nope"})
    assert client.get(url).status_code == 404


def test_unknown_record_type_is_404(client, world, admin_client_user):
    url = reverse("teacher_registration:teacher_record_add", kwargs={"pk": world.teacher.pk, "rtype": "nope"})
    assert client.get(url).status_code == 404


def test_assignment_record_routes_redirect_to_dedicated_views(client, world, admin_client_user):
    add = reverse("teacher_registration:teacher_record_add", kwargs={"pk": world.teacher.pk, "rtype": "assignment"})
    response = client.get(add)
    assert response.status_code == 302
    assert response["Location"] == reverse("teacher_registration:teacher_assignment_add", kwargs={"pk": world.teacher.pk})

    edit = reverse(
        "teacher_registration:teacher_record_edit",
        kwargs={"pk": world.teacher.pk, "rtype": "assignment", "record_pk": world.assignment.pk},
    )
    response = client.get(edit)
    assert response["Location"] == reverse(
        "teacher_registration:teacher_assignment_edit",
        kwargs={"pk": world.teacher.pk, "assignment_pk": world.assignment.pk},
    )


def test_non_teaching_staff_is_not_a_teacher(client, world, admin_client_user):
    """Teacher pages only resolve SchoolStaff rows flagged as teaching staff."""
    assert client.get(reverse("teacher_registration:teacher_detail", kwargs={"pk": world.staff.pk})).status_code == 404


def test_missing_objects_are_404(client, world, admin_client_user):
    for name, kwargs in [
        ("core:staff_detail", {"pk": 999999}),
        ("core:system_user_detail", {"pk": 999999}),
        ("teacher_registration:edit", {"pk": 999999}),
        ("teacher_registration:review", {"pk": 999999}),
        ("teacher_registration:teacher_detail", {"pk": 999999}),
    ]:
        assert client.get(reverse(name, kwargs=kwargs)).status_code == 404, name


def test_review_page_refuses_draft(client, world, admin_client_user):
    response = client.get(reverse("teacher_registration:review", kwargs={"pk": world.draft.pk}))
    assert response.status_code == 302
    assert response["Location"] == reverse("teacher_registration:pending_list")


def test_school_scoped_roles_can_view_staff_at_their_school(client, world):
    viewer = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[world.membership.school])
    client.force_login(viewer)
    assert client.get(reverse("core:staff_detail", kwargs={"pk": world.staff.pk})).status_code == 200
    assert client.get(reverse("core:staff_edit", kwargs={"pk": world.staff.pk})).status_code == 200


def test_pdf_split_rejects_malformed_job_id(client, admin_client_user):
    assert client.get(reverse("core:pdf_split_results", kwargs={"job_id": "not-hex"})).status_code == 403
