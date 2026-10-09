"""
Permissions matrix: every predicate in core.permissions against every role.

Roles are built from the two profile types (SchoolStaff, SystemUser) and the
group names in core.permissions. Each test either tabulates expected answers
per role, or exercises the school-scoped row-level rules with two schools.
"""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db.models import OuterRef, Subquery

from core import permissions as p
from core.models import SchoolStaff, SchoolStaffAssignment
from core.tests.factories import (
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    UserFactory,
    add_to_groups,
    school_staff_user,
    system_user,
)
from integrations.models import EmisSchool
from integrations.tests.factories import EmisSchoolFactory

pytestmark = pytest.mark.django_db

ROLE_NAMES = [
    "anonymous",
    "superuser",
    "admins",
    "system_admins",
    "system_staff",
    "school_admins",
    "teachers",
    "school_staff",
    "profile_no_group",
    "group_no_profile",
]


def build_role(name):
    """Create a user for the named role. Returns a fresh user each call."""
    if name == "anonymous":
        return AnonymousUser()
    if name == "superuser":
        return UserFactory(is_superuser=True, is_staff=True)
    if name == "admins":
        return school_staff_user(p.GROUP_ADMINS)
    if name == "system_admins":
        return system_user(p.GROUP_SYSTEM_ADMINS)
    if name == "system_staff":
        return system_user(p.GROUP_SYSTEM_STAFF)
    if name == "school_admins":
        return school_staff_user(p.GROUP_SCHOOL_ADMINS)
    if name == "teachers":
        return school_staff_user(p.GROUP_TEACHERS)
    if name == "school_staff":
        return school_staff_user(p.GROUP_SCHOOL_STAFF)
    if name == "profile_no_group":
        return school_staff_user()
    if name == "group_no_profile":
        return add_to_groups(UserFactory(), p.GROUP_TEACHERS)
    raise ValueError(name)


@pytest.fixture
def role(request):
    return build_role(request.param)


def matrix(**expected):
    """Parametrize over ROLE_NAMES with the expected boolean for each role."""
    missing = set(ROLE_NAMES) - set(expected)
    assert not missing, f"matrix is missing roles: {missing}"
    return pytest.mark.parametrize(
        ("role", "expected"),
        [(name, expected[name]) for name in ROLE_NAMES],
        indirect=["role"],
        ids=ROLE_NAMES,
    )


# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=True,
    system_staff=False, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_is_admin(role, expected):
    assert p.is_admin(role) is expected
    assert p.is_inclusive_admin(role) is expected


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=False,
    system_staff=False, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_is_admins_group(role, expected):
    assert p.is_admins_group(role) is expected


@matrix(
    anonymous=False, superuser=False, admins=False, system_admins=False,
    system_staff=False, school_admins=True, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_is_school_admin(role, expected):
    assert p.is_school_admin(role) is expected
    assert p.is_inclusive_school_admin(role) is expected


@matrix(
    anonymous=False, superuser=False, admins=False, system_admins=False,
    system_staff=False, school_admins=False, teachers=True, school_staff=False,
    profile_no_group=False, group_no_profile=True,
)
def test_is_teacher(role, expected):
    assert p.is_teacher(role) is expected
    assert p.is_inclusive_teacher(role) is expected


@matrix(
    anonymous=False, superuser=False, admins=False, system_admins=False,
    system_staff=False, school_admins=False, teachers=False, school_staff=True,
    profile_no_group=False, group_no_profile=False,
)
def test_is_school_staff(role, expected):
    assert p.is_school_staff(role) is expected
    assert p.is_inclusive_staff(role) is expected


@matrix(
    anonymous=False, superuser=False, admins=False, system_admins=False,
    system_staff=True, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_is_system_staff(role, expected):
    assert p.is_system_staff(role) is expected


# ---------------------------------------------------------------------------
# App-level access
# ---------------------------------------------------------------------------


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=True,
    system_staff=True, school_admins=True, teachers=True, school_staff=True,
    profile_no_group=False, group_no_profile=False,
)
def test_has_app_access(role, expected):
    assert p.has_app_access(role) is expected


def test_has_app_access_with_system_user_profile_and_group():
    assert p.has_app_access(system_user(p.GROUP_SYSTEM_STAFF)) is True


def test_has_app_access_requires_group_even_for_system_user_profile():
    assert p.has_app_access(system_user()) is False


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=True,
    system_staff=True, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_can_access_system_users(role, expected):
    assert p.can_access_system_users(role) is expected


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=True,
    system_staff=False, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_can_manage_pending_users(role, expected):
    assert p.can_manage_pending_users(role) is expected


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=False,
    system_staff=False, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_can_assign_admins_group(role, expected):
    """System Admins must not be able to elevate anyone to Admins."""
    assert p.can_assign_admins_group(role) is expected


@matrix(
    anonymous=False, superuser=True, admins=True, system_admins=True,
    system_staff=False, school_admins=False, teachers=False, school_staff=False,
    profile_no_group=False, group_no_profile=False,
)
def test_can_edit_system_user(role, expected):
    target = system_user(p.GROUP_SYSTEM_STAFF).system_user
    assert p.can_edit_system_user(role, target) is expected
    assert p.can_edit_system_user_groups(role, target) is expected


# ---------------------------------------------------------------------------
# School-scoped helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def schools():
    return EmisSchoolFactory(emis_school_no="SCH-A"), EmisSchoolFactory(emis_school_no="SCH-B")


class TestGetUserSchools:
    def test_anonymous_has_no_schools(self):
        assert list(p.get_user_schools(AnonymousUser())) == []

    def test_user_without_school_staff_profile_has_no_schools(self):
        assert list(p.get_user_schools(system_user(p.GROUP_SYSTEM_ADMINS))) == []

    def test_returns_only_schools_with_open_assignments(self, schools):
        school_a, school_b = schools
        staff = SchoolStaffFactory()
        SchoolStaffAssignmentFactory(school_staff=staff, school=school_a, end_date=None)
        SchoolStaffAssignmentFactory(
            school_staff=staff, school=school_b, end_date=date.today() + timedelta(days=30)
        )
        assert list(p.get_user_schools(staff.user)) == [school_a]

    def test_multiple_assignments_at_one_school_are_distinct(self, schools):
        school_a, _ = schools
        staff = SchoolStaffFactory()
        SchoolStaffAssignmentFactory(school_staff=staff, school=school_a, start_date=date(2020, 1, 1))
        SchoolStaffAssignmentFactory(school_staff=staff, school=school_a, start_date=date(2022, 1, 1))
        assert list(p.get_user_schools(staff.user)) == [school_a]


class TestStaffRowLevelAccess:
    """can_view_staff, user_has_school_access_to_staff, can_edit_staff, can_edit_staff_groups."""

    @pytest.fixture
    def staff_at_a(self, schools):
        school_a, _ = schools
        return school_staff_user(p.GROUP_TEACHERS, schools=[school_a]).school_staff

    @pytest.mark.parametrize("group", [p.GROUP_SCHOOL_ADMINS, p.GROUP_TEACHERS])
    def test_shared_school_grants_access(self, schools, staff_at_a, group):
        school_a, _ = schools
        viewer = school_staff_user(group, schools=[school_a])
        assert p.user_has_school_access_to_staff(viewer, staff_at_a) is True
        assert p.can_view_staff(viewer, staff_at_a) is True

    @pytest.mark.parametrize("group", [p.GROUP_SCHOOL_ADMINS, p.GROUP_TEACHERS])
    def test_different_school_denies_access(self, schools, staff_at_a, group):
        _, school_b = schools
        viewer = school_staff_user(group, schools=[school_b])
        assert p.user_has_school_access_to_staff(viewer, staff_at_a) is False
        assert p.can_view_staff(viewer, staff_at_a) is False

    def test_viewer_without_any_school_is_denied(self, staff_at_a):
        viewer = school_staff_user(p.GROUP_SCHOOL_ADMINS)
        assert p.user_has_school_access_to_staff(viewer, staff_at_a) is False

    def test_target_without_any_school_is_denied(self, schools):
        school_a, _ = schools
        viewer = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_a])
        target = SchoolStaffFactory()
        assert p.user_has_school_access_to_staff(viewer, target) is False

    def test_ended_assignment_does_not_grant_access(self, schools, staff_at_a):
        school_a, _ = schools
        viewer = school_staff_user(p.GROUP_SCHOOL_ADMINS)
        SchoolStaffAssignmentFactory(
            school_staff=viewer.school_staff, school=school_a, end_date=date.today()
        )
        assert p.can_view_staff(viewer, staff_at_a) is False

    def test_admin_and_superuser_always_have_access(self, staff_at_a):
        for user in (
            UserFactory(is_superuser=True),
            school_staff_user(p.GROUP_ADMINS),
            system_user(p.GROUP_SYSTEM_ADMINS),
        ):
            assert p.can_view_staff(user, staff_at_a) is True
            assert p.can_edit_staff(user, staff_at_a) is True
            assert p.can_edit_staff_groups(user, staff_at_a) is True

    def test_school_staff_group_cannot_view_even_at_same_school(self, schools, staff_at_a):
        school_a, _ = schools
        viewer = school_staff_user(p.GROUP_SCHOOL_STAFF, schools=[school_a])
        assert p.can_view_staff(viewer, staff_at_a) is False

    def test_system_staff_cannot_view(self, staff_at_a):
        assert p.can_view_staff(system_user(p.GROUP_SYSTEM_STAFF), staff_at_a) is False

    def test_anonymous_cannot_view(self, staff_at_a):
        assert p.can_view_staff(AnonymousUser(), staff_at_a) is False

    def test_school_admin_can_edit_staff_at_own_school_only(self, schools, staff_at_a):
        school_a, school_b = schools
        same = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_a])
        other = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_b])
        assert p.can_edit_staff(same, staff_at_a) is True
        assert p.can_edit_staff_groups(same, staff_at_a) is True
        assert p.can_edit_staff(other, staff_at_a) is False
        assert p.can_edit_staff_groups(other, staff_at_a) is False

    def test_teacher_cannot_edit_staff_even_at_same_school(self, schools, staff_at_a):
        school_a, _ = schools
        teacher = school_staff_user(p.GROUP_TEACHERS, schools=[school_a])
        assert p.can_edit_staff(teacher, staff_at_a) is False
        assert p.can_edit_staff_groups(teacher, staff_at_a) is False


class TestFilterStaffForUser:
    """The list-view filter relies on a latest_school_no annotation from the view."""

    @staticmethod
    def annotated_queryset():
        latest = SchoolStaffAssignment.objects.filter(school_staff=OuterRef("pk")).order_by(
            "-start_date"
        )
        return SchoolStaff.objects.annotate(
            latest_school_no=Subquery(latest.values("school__emis_school_no")[:1])
        )

    @pytest.fixture
    def population(self, schools):
        school_a, school_b = schools
        staff_a = school_staff_user(p.GROUP_TEACHERS, schools=[school_a]).school_staff
        staff_b = school_staff_user(p.GROUP_TEACHERS, schools=[school_b]).school_staff
        unassigned = SchoolStaffFactory()
        return {"a": staff_a, "b": staff_b, "none": unassigned}

    def test_anonymous_sees_nothing(self, population):
        assert not p.filter_staff_for_user(self.annotated_queryset(), AnonymousUser()).exists()

    @pytest.mark.parametrize("builder", [
        lambda: UserFactory(is_superuser=True),
        lambda: school_staff_user(p.GROUP_ADMINS),
        lambda: system_user(p.GROUP_SYSTEM_ADMINS),
    ])
    def test_admins_see_everything(self, population, builder):
        qs = p.filter_staff_for_user(self.annotated_queryset(), builder())
        assert set(population.values()) <= set(qs)

    @pytest.mark.parametrize("group", [p.GROUP_SCHOOL_ADMINS, p.GROUP_TEACHERS])
    def test_school_scoped_roles_see_only_their_school(self, schools, population, group):
        school_a, _ = schools
        viewer = school_staff_user(group, schools=[school_a])
        qs = p.filter_staff_for_user(self.annotated_queryset(), viewer)
        assert population["a"] in qs
        assert population["b"] not in qs
        assert population["none"] not in qs

    @pytest.mark.parametrize("group", [p.GROUP_SCHOOL_ADMINS, p.GROUP_TEACHERS])
    def test_school_scoped_role_without_school_sees_nothing(self, population, group):
        viewer = school_staff_user(group)
        assert not p.filter_staff_for_user(self.annotated_queryset(), viewer).exists()

    def test_school_staff_and_system_staff_see_nothing(self, schools, population):
        school_a, _ = schools
        for viewer in (
            school_staff_user(p.GROUP_SCHOOL_STAFF, schools=[school_a]),
            system_user(p.GROUP_SYSTEM_STAFF),
        ):
            assert not p.filter_staff_for_user(self.annotated_queryset(), viewer).exists()

    def test_filter_uses_latest_assignment(self, schools, population):
        """A staff member who moved from B to A is visible to school A, not B."""
        school_a, school_b = schools
        mover = SchoolStaffFactory()
        SchoolStaffAssignmentFactory(
            school_staff=mover, school=school_b, start_date=date(2020, 1, 1), end_date=date(2021, 12, 31)
        )
        SchoolStaffAssignmentFactory(school_staff=mover, school=school_a, start_date=date(2022, 1, 1))
        viewer_a = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_a])
        viewer_b = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_b])
        assert mover in p.filter_staff_for_user(self.annotated_queryset(), viewer_a)
        assert mover not in p.filter_staff_for_user(self.annotated_queryset(), viewer_b)


class TestMembershipPermissions:
    """can_create_staff_membership, can_edit_staff_membership, can_delete_staff_membership."""

    @pytest.fixture
    def membership_at_a(self, schools):
        school_a, _ = schools
        return SchoolStaffAssignmentFactory(school=school_a)

    def test_admins_can_do_everything(self, schools, membership_at_a):
        school_a, _ = schools
        for user in (
            UserFactory(is_superuser=True),
            school_staff_user(p.GROUP_ADMINS),
            system_user(p.GROUP_SYSTEM_ADMINS),
        ):
            assert p.can_create_staff_membership(user) is True
            assert p.can_create_staff_membership(user, school_a) is True
            assert p.can_edit_staff_membership(user, membership_at_a) is True
            assert p.can_delete_staff_membership(user, membership_at_a) is True

    def test_school_admin_scoped_to_own_schools(self, schools, membership_at_a):
        school_a, school_b = schools
        admin_a = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_a])
        assert p.can_create_staff_membership(admin_a, school_a) is True
        assert p.can_create_staff_membership(admin_a, school_b) is False
        assert p.can_edit_staff_membership(admin_a, membership_at_a) is True
        assert p.can_delete_staff_membership(admin_a, membership_at_a) is True

        admin_b = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[school_b])
        assert p.can_edit_staff_membership(admin_b, membership_at_a) is False
        assert p.can_delete_staff_membership(admin_b, membership_at_a) is False

    def test_school_admin_without_target_school_may_attempt_create(self):
        """Characterises current behaviour: school validation happens later in the view."""
        admin = school_staff_user(p.GROUP_SCHOOL_ADMINS)
        assert p.can_create_staff_membership(admin) is True
        assert p.can_create_staff_membership(admin, EmisSchoolFactory()) is False

    @pytest.mark.parametrize(
        "builder",
        [
            lambda: AnonymousUser(),
            lambda: school_staff_user(p.GROUP_TEACHERS),
            lambda: school_staff_user(p.GROUP_SCHOOL_STAFF),
            lambda: system_user(p.GROUP_SYSTEM_STAFF),
            lambda: school_staff_user(),
        ],
    )
    def test_other_roles_denied(self, schools, membership_at_a, builder):
        school_a, _ = schools
        user = builder()
        assert p.can_create_staff_membership(user) is False
        assert p.can_create_staff_membership(user, school_a) is False
        assert p.can_edit_staff_membership(user, membership_at_a) is False
        assert p.can_delete_staff_membership(user, membership_at_a) is False


def test_group_name_constants_are_stable():
    """Group names are stored in the database; renaming one is a data migration."""
    assert p.GROUP_ADMINS == "Admins"
    assert p.GROUP_SCHOOL_ADMINS == "School Admins"
    assert p.GROUP_SCHOOL_STAFF == "School Staff"
    assert p.GROUP_TEACHERS == "Teachers"
    assert p.GROUP_SYSTEM_ADMINS == "System Admins"
    assert p.GROUP_SYSTEM_STAFF == "System Staff"
    assert p.GROUP_REGISTRATION_SIGNATORIES == "Registration Signatories"


def test_legacy_aliases_point_at_current_names():
    assert p.GROUP_INCLUSIVE_ADMINS == p.GROUP_ADMINS
    assert p.GROUP_INCLUSIVE_SCHOOL_ADMINS == p.GROUP_SCHOOL_ADMINS
    assert p.GROUP_INCLUSIVE_STAFF == p.GROUP_SCHOOL_STAFF
    assert p.GROUP_INCLUSIVE_TEACHERS == p.GROUP_TEACHERS


def test_emis_school_queryset_type_for_anonymous():
    assert p.get_user_schools(None).model is EmisSchool
