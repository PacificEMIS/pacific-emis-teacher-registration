"""Factories for EMIS lookup models."""

import factory

from integrations import models as m


class EmisSchoolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = m.EmisSchool
        django_get_or_create = ("emis_school_no",)

    emis_school_no = factory.Sequence(lambda n: f"SCH{n:03d}")
    emis_school_name = factory.LazyAttribute(lambda o: f"School {o.emis_school_no}")
    active = True


def _lookup_factory(model, prefix):
    """Build a factory class for a simple code/label/active lookup model."""

    class Meta:
        pass

    Meta.model = model
    Meta.django_get_or_create = ("code",)

    return type(
        f"{model.__name__}Factory",
        (factory.django.DjangoModelFactory,),
        {
            "Meta": Meta,
            "code": factory.Sequence(lambda n: f"{prefix}{n:03d}"),
            "label": factory.LazyAttribute(lambda o: f"{prefix} {o.code}"),
            "active": True,
        },
    )


EmisJobTitleFactory = _lookup_factory(m.EmisJobTitle, "JOB")
EmisClassLevelFactory = _lookup_factory(m.EmisClassLevel, "LVL")
EmisSubjectFactory = _lookup_factory(m.EmisSubject, "SUBJ")
EmisTeacherQualFactory = _lookup_factory(m.EmisTeacherQual, "QUAL")
EmisMaritalStatusFactory = _lookup_factory(m.EmisMaritalStatus, "MAR")
EmisIslandFactory = _lookup_factory(m.EmisIsland, "ISL")
EmisTeacherStatusFactory = _lookup_factory(m.EmisTeacherStatus, "TSTAT")
EmisEducationLevelFactory = _lookup_factory(m.EmisEducationLevel, "EDL")
EmisGenderFactory = _lookup_factory(m.EmisGender, "GEN")
EmisTeacherPdFocusFactory = _lookup_factory(m.EmisTeacherPdFocus, "PDF")
EmisTeacherPdFormatFactory = _lookup_factory(m.EmisTeacherPdFormat, "PDFMT")
EmisTeacherPdTypeFactory = _lookup_factory(m.EmisTeacherPdType, "PDT")
EmisNationalityFactory = _lookup_factory(m.EmisNationality, "NAT")


class EmisTeacherLinkTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = m.EmisTeacherLinkType
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"LINK{n:03d}")
    label = factory.LazyAttribute(lambda o: f"Link {o.code}")
    active = True


class EmisTeacherRegistrationStatusFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = m.EmisTeacherRegistrationStatus
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"REG{n:03d}")
    label = factory.LazyAttribute(lambda o: f"Status {o.code}")
    active = True
    validity_value = None
    validity_unit = ""
