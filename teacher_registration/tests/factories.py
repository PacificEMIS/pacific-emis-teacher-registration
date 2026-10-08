"""Factories for registrations and their child records."""

from datetime import date

import factory

from core.tests.factories import UserFactory
from integrations.tests.factories import (
    EmisClassLevelFactory,
    EmisEducationLevelFactory,
    EmisGenderFactory,
    EmisJobTitleFactory,
    EmisSchoolFactory,
    EmisSubjectFactory,
    EmisTeacherLinkTypeFactory,
    EmisTeacherPdFocusFactory,
    EmisTeacherPdFormatFactory,
    EmisTeacherQualFactory,
    EmisTeacherStatusFactory,
)
from teacher_registration import constants
from teacher_registration.models import (
    ClaimedDuty,
    ClaimedSchoolAppointment,
    EducationRecord,
    LookupCondition,
    RegistrationCondition,
    RegistrationDocument,
    TeacherRegistration,
    TrainingRecord,
)


class TeacherRegistrationFactory(factory.django.DjangoModelFactory):
    """A draft initial registration with enough data to be approved."""

    class Meta:
        model = TeacherRegistration

    user = factory.SubFactory(UserFactory)
    registration_type = TeacherRegistration.INITIAL
    teacher_category = TeacherRegistration.NEW_TEACHER
    status = constants.DRAFT
    title = TeacherRegistration.TITLE_MR
    date_of_birth = date(1990, 5, 17)
    gender = factory.SubFactory(EmisGenderFactory)
    national_id_number = factory.Sequence(lambda n: f"NID{n:06d}")
    phone_number = "+686 12345"
    residential_address = "1 Main Road"
    highest_qualification = "bachelors"
    years_of_experience = 3

    class Params:
        submitted = factory.Trait(status=constants.SUBMITTED)
        under_review = factory.Trait(status=constants.UNDER_REVIEW)
        ready = factory.Trait(status=constants.READY_FOR_APPROVAL)
        renewal = factory.Trait(
            registration_type=TeacherRegistration.RENEWAL,
            teacher_category=TeacherRegistration.CURRENT_TEACHER,
        )


class EducationRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EducationRecord

    registration = factory.SubFactory(TeacherRegistrationFactory)
    institution_name = factory.Sequence(lambda n: f"University {n}")
    qualification = factory.SubFactory(EmisTeacherQualFactory)
    program_name = "Bachelor of Education"
    major = factory.SubFactory(EmisSubjectFactory)
    completion_year = 2015
    duration = 4
    duration_unit = EducationRecord.YEARS
    completed = True


class TrainingRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrainingRecord

    registration = factory.SubFactory(TeacherRegistrationFactory)
    provider_institution = factory.Sequence(lambda n: f"Provider {n}")
    title = factory.Sequence(lambda n: f"Workshop {n}")
    focus = factory.SubFactory(EmisTeacherPdFocusFactory)
    format = factory.SubFactory(EmisTeacherPdFormatFactory)
    completion_year = 2020
    duration = 3
    duration_unit = TrainingRecord.DAYS


class ClaimedSchoolAppointmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClaimedSchoolAppointment

    registration = factory.SubFactory(TeacherRegistrationFactory)
    teacher_level_type = factory.SubFactory(EmisEducationLevelFactory)
    current_school = factory.SubFactory(EmisSchoolFactory)
    employment_position = factory.SubFactory(EmisJobTitleFactory)
    employment_status = factory.SubFactory(EmisTeacherStatusFactory)
    start_date = date(2021, 2, 1)


class ClaimedDutyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClaimedDuty

    appointment = factory.SubFactory(ClaimedSchoolAppointmentFactory)
    year_level = factory.SubFactory(EmisClassLevelFactory)
    subject = factory.SubFactory(EmisSubjectFactory)


class RegistrationDocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegistrationDocument

    registration = factory.SubFactory(TeacherRegistrationFactory)
    school_staff = None
    file = factory.django.FileField(filename="document.pdf", data=b"%PDF-1.4 test")
    original_filename = "document.pdf"
    file_size = 13
    doc_link_type = factory.SubFactory(EmisTeacherLinkTypeFactory)
    doc_type = "pdf"


class LookupConditionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LookupCondition
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"COND{n:03d}")
    label = factory.LazyAttribute(lambda o: f"Condition {o.code}")
    active = True


class RegistrationConditionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegistrationCondition

    registration = factory.SubFactory(TeacherRegistrationFactory)
    school_staff = None
    condition = factory.SubFactory(LookupConditionFactory)
    notes = "Complete within the year"
