"""Factories for EMIS lookup models."""

import factory

from integrations.models import (
    EmisJobTitle,
    EmisSchool,
    EmisTeacherRegistrationStatus,
)


class EmisSchoolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisSchool
        django_get_or_create = ("emis_school_no",)

    emis_school_no = factory.Sequence(lambda n: f"SCH{n:03d}")
    emis_school_name = factory.LazyAttribute(lambda o: f"School {o.emis_school_no}")
    active = True


class EmisJobTitleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisJobTitle
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"JOB{n:03d}")
    label = factory.LazyAttribute(lambda o: f"Job {o.code}")
    active = True


class EmisTeacherRegistrationStatusFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisTeacherRegistrationStatus
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"REG{n:03d}")
    label = factory.LazyAttribute(lambda o: f"Status {o.code}")
    active = True
    validity_value = None
    validity_unit = ""
