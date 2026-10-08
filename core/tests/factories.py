"""Factories for users, profiles, groups and school assignments."""

import factory
from django.contrib.auth.models import Group, User

from core.models import SchoolStaff, SchoolStaffAssignment, SystemUser
from integrations.tests.factories import EmisJobTitleFactory, EmisSchoolFactory


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}@example.org")
    email = factory.LazyAttribute(lambda o: o.username)
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")
    password = factory.django.Password("password")
    is_active = True


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Group {n}")


class SchoolStaffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolStaff

    user = factory.SubFactory(UserFactory)


class SystemUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SystemUser

    user = factory.SubFactory(UserFactory)


class SchoolStaffAssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolStaffAssignment

    school_staff = factory.SubFactory(SchoolStaffFactory)
    school = factory.SubFactory(EmisSchoolFactory)
    job_title = factory.SubFactory(EmisJobTitleFactory)
    start_date = None
    end_date = None


def add_to_groups(user, *group_names):
    """Put a user in the named groups, creating any that do not exist yet."""
    for name in group_names:
        user.groups.add(GroupFactory(name=name))
    return user


def school_staff_user(*group_names, schools=()):
    """A user with a SchoolStaff profile, the given groups and active assignments."""
    staff = SchoolStaffFactory()
    add_to_groups(staff.user, *group_names)
    for school in schools:
        SchoolStaffAssignmentFactory(school_staff=staff, school=school)
    return staff.user


def system_user(*group_names):
    """A user with a SystemUser profile and the given groups."""
    profile = SystemUserFactory()
    add_to_groups(profile.user, *group_names)
    return profile.user
