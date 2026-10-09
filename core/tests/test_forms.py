"""Form tests for core: group offerings per role, school scoping, and initial values."""

import pytest
from django.contrib.auth.models import AnonymousUser

from core import permissions as p
from core.forms import (
    AssignSchoolStaffForm,
    AssignSystemUserForm,
    OrgSettingsForm,
    SchoolStaffAssignmentForm,
    SchoolStaffEditForm,
    SystemUserEditForm,
    TestEmailForm,
)
from core.models import SchoolStaff
from core.tests.factories import (
    GroupFactory,
    SchoolStaffFactory,
    SystemUserFactory,
    UserFactory,
    school_staff_user,
    system_user,
)
from integrations.tests.factories import EmisEducationLevelFactory, EmisJobTitleFactory, EmisSchoolFactory

pytestmark = pytest.mark.django_db

SCHOOL_GROUPS = [p.GROUP_ADMINS, p.GROUP_SCHOOL_ADMINS, p.GROUP_SCHOOL_STAFF, p.GROUP_TEACHERS, p.GROUP_REGISTRATION_SIGNATORIES]
SYSTEM_GROUPS = [p.GROUP_ADMINS, p.GROUP_SYSTEM_ADMINS, p.GROUP_SYSTEM_STAFF, p.GROUP_REGISTRATION_SIGNATORIES]


@pytest.fixture
def groups():
    return {name: GroupFactory(name=name) for name in set(SCHOOL_GROUPS + SYSTEM_GROUPS)}


def offered(form):
    return set(form.fields["groups"].queryset.values_list("name", flat=True))


class TestSchoolStaffAssignmentForm:
    def test_admin_sees_all_active_schools(self):
        active = EmisSchoolFactory(active=True)
        EmisSchoolFactory(active=False)
        for user in (UserFactory(is_superuser=True), school_staff_user(p.GROUP_ADMINS), system_user(p.GROUP_SYSTEM_ADMINS)):
            assert list(SchoolStaffAssignmentForm(user=user).fields["school"].queryset) == [active]

    def test_school_admin_sees_only_own_schools(self):
        own, other = EmisSchoolFactory(), EmisSchoolFactory()
        admin = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[own])
        assert list(SchoolStaffAssignmentForm(user=admin).fields["school"].queryset) == [own]
        form = SchoolStaffAssignmentForm({"school": other.pk, "job_title": EmisJobTitleFactory().pk}, user=admin)
        assert "school" in form.errors

    def test_no_user_or_anonymous_sees_nothing(self):
        EmisSchoolFactory()
        assert not SchoolStaffAssignmentForm().fields["school"].queryset.exists()
        assert not SchoolStaffAssignmentForm(user=AnonymousUser()).fields["school"].queryset.exists()

    def test_valid_submission(self):
        school, job, level = EmisSchoolFactory(), EmisJobTitleFactory(), EmisEducationLevelFactory()
        form = SchoolStaffAssignmentForm(
            {
                "school": school.pk,
                "job_title": job.pk,
                "teacher_level_type": level.pk,
                "start_date": "2026-01-01",
                "end_date": "",
            },
            user=UserFactory(is_superuser=True),
        )
        assert form.is_valid(), form.errors

    def test_education_level_is_required_and_limited_to_active(self):
        active = EmisEducationLevelFactory(active=True)
        EmisEducationLevelFactory(active=False)
        form = SchoolStaffAssignmentForm(user=UserFactory(is_superuser=True))
        assert list(form.fields["teacher_level_type"].queryset) == [active]
        form = SchoolStaffAssignmentForm(
            {"school": EmisSchoolFactory().pk, "job_title": EmisJobTitleFactory().pk},
            user=UserFactory(is_superuser=True),
        )
        assert "teacher_level_type" in form.errors


class TestSchoolStaffEditForm:
    def test_admins_may_assign_admins_group(self, groups):
        for user in (UserFactory(is_superuser=True), school_staff_user(p.GROUP_ADMINS)):
            form = SchoolStaffEditForm(user=user)
            assert form.can_assign_admins is True
            assert offered(form) == set(SCHOOL_GROUPS)

    def test_system_and_school_admins_may_not(self, groups):
        for user in (system_user(p.GROUP_SYSTEM_ADMINS), school_staff_user(p.GROUP_SCHOOL_ADMINS)):
            form = SchoolStaffEditForm(user=user)
            assert form.can_assign_admins is False
            assert p.GROUP_ADMINS not in offered(form)
            assert "Only full Admins" in form.fields["groups"].help_text

    def test_initial_from_school_staff_ignores_system_groups(self, groups):
        staff = SchoolStaffFactory(staff_type=SchoolStaff.TEACHING_STAFF)
        staff.user.groups.add(groups[p.GROUP_TEACHERS], groups[p.GROUP_SYSTEM_STAFF])
        form = SchoolStaffEditForm(user=UserFactory(is_superuser=True), school_staff=staff)
        assert form.initial["staff_type"] == SchoolStaff.TEACHING_STAFF
        assert list(form.initial["groups"].values_list("name", flat=True)) == [p.GROUP_TEACHERS]

    def test_groups_required(self, groups):
        form = SchoolStaffEditForm({"staff_type": SchoolStaff.TEACHING_STAFF}, user=UserFactory(is_superuser=True))
        assert "groups" in form.errors


class TestAssignForms:
    def test_assign_school_staff_offerings(self, groups):
        assert offered(AssignSchoolStaffForm(user=school_staff_user(p.GROUP_ADMINS))) == set(SCHOOL_GROUPS)
        form = AssignSchoolStaffForm(user=system_user(p.GROUP_SYSTEM_ADMINS))
        assert offered(form) == set(SCHOOL_GROUPS) - {p.GROUP_ADMINS}
        assert AssignSchoolStaffForm().can_assign_admins is False

    def test_assign_school_staff_defaults_and_validation(self, groups):
        form = AssignSchoolStaffForm(user=UserFactory(is_superuser=True))
        assert form.fields["staff_type"].initial == SchoolStaff.NON_TEACHING_STAFF
        bound = AssignSchoolStaffForm(
            {"staff_type": SchoolStaff.TEACHING_STAFF, "groups": [groups[p.GROUP_TEACHERS].pk]},
            user=UserFactory(is_superuser=True),
        )
        assert bound.is_valid(), bound.errors

    def test_assign_system_user_offerings(self, groups):
        assert offered(AssignSystemUserForm(user=school_staff_user(p.GROUP_ADMINS))) == set(SYSTEM_GROUPS)
        form = AssignSystemUserForm(user=system_user(p.GROUP_SYSTEM_ADMINS))
        assert offered(form) == set(SYSTEM_GROUPS) - {p.GROUP_ADMINS}

    def test_assign_system_user_optional_text_fields(self, groups):
        form = AssignSystemUserForm({"groups": [groups[p.GROUP_SYSTEM_STAFF].pk]}, user=UserFactory(is_superuser=True))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["organization"] == ""


class TestSystemUserEditForm:
    def test_offerings_by_role(self, groups):
        assert offered(SystemUserEditForm(user=school_staff_user(p.GROUP_ADMINS))) == set(SYSTEM_GROUPS)
        assert p.GROUP_ADMINS not in offered(SystemUserEditForm(user=system_user(p.GROUP_SYSTEM_ADMINS)))

    def test_initial_from_system_user(self, groups):
        profile = SystemUserFactory(organization="MoE", position_title="Registrar")
        profile.user.groups.add(groups[p.GROUP_SYSTEM_STAFF], groups[p.GROUP_TEACHERS])
        form = SystemUserEditForm(user=UserFactory(is_superuser=True), system_user=profile)
        assert form.initial["organization"] == "MoE"
        assert form.initial["position_title"] == "Registrar"
        assert list(form.initial["groups"].values_list("name", flat=True)) == [p.GROUP_SYSTEM_STAFF]

    def test_bound_form_does_not_overwrite_initial(self, groups):
        profile = SystemUserFactory(organization="MoE")
        form = SystemUserEditForm({"organization": "Other", "groups": []}, user=UserFactory(is_superuser=True), system_user=profile)
        assert "organization" not in form.initial


def test_org_settings_form_only_edits_stamp():
    assert OrgSettingsForm.Meta.fields == ["stamp"]
    assert OrgSettingsForm({}).is_valid()


def test_test_email_form():
    assert TestEmailForm({"recipient": "a@example.org"}).is_valid()
    assert "recipient" in TestEmailForm({"recipient": "nope"}).errors
    assert "recipient" in TestEmailForm({}).errors
