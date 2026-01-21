from django.core.management.base import BaseCommand
from django.db import transaction
from integrations.models import (
    EmisSchool,
    EmisClassLevel,
    EmisJobTitle,
    EmisWarehouseYear,
    EmisSubject,
    EmisTeacherQual,
    EmisMaritalStatus,
    EmisIsland,
    EmisTeacherStatus,
    EmisEducationLevel,
    EmisTeacherLinkType,
    EmisGender,
    EmisTeacherPdFocus,
    EmisTeacherPdFormat,
    EmisTeacherPdType,
)
from integrations.emis_client import EmisClient


class Command(BaseCommand):
    help = "Fetch /api/lookups/collection/core and update local lookup tables"

    def handle(self, *args, **options):
        client = EmisClient()
        payload = client.get_core_lookups()

        schools = payload.get("schoolCodes", [])
        levels = payload.get("levels", [])
        job_titles = payload.get("teacherRoles", [])
        warehouse_years = payload.get("warehouseYears", [])
        subjects = payload.get("subjects", [])
        teacher_quals = payload.get("teacherQuals", [])
        marital_statuses = payload.get("maritalStatus", [])
        islands = payload.get("islands", [])
        teacher_statuses = payload.get("teacherRegStatus", [])
        education_levels = payload.get("educationLevels", [])
        teacher_link_types = payload.get("teacherLinkTypes", [])
        genders = payload.get("gender", [])
        pd_focuses = payload.get("teacherPdFocuses", [])
        pd_formats = payload.get("teacherPdFormats", [])
        pd_types = payload.get("teacherPdTypes", [])

        # Counters: (added, updated) for each entity
        counts = {
            "schools": [0, 0],
            "levels": [0, 0],
            "job_titles": [0, 0],
            "years": [0, 0],
            "subjects": [0, 0],
            "teacher_quals": [0, 0],
            "marital_status": [0, 0],
            "islands": [0, 0],
            "teacher_status": [0, 0],
            "education_levels": [0, 0],
            "teacher_link_types": [0, 0],
            "genders": [0, 0],
            "pd_focuses": [0, 0],
            "pd_formats": [0, 0],
            "pd_types": [0, 0],
        }

        with transaction.atomic():
            # Schools
            for item in schools:
                code, name = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisSchool.objects.update_or_create(
                    emis_school_no=code,
                    defaults={"emis_school_name": name or "", "active": True},
                )
                counts["schools"][0 if created else 1] += 1

            # Class Levels
            for item in levels:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisClassLevel.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["levels"][0 if created else 1] += 1

            # Job Titles
            for item in job_titles:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisJobTitle.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["job_titles"][0 if created else 1] += 1

            # Warehouse Years
            for item in warehouse_years:
                code, label = item.get("C"), item.get("FormattedYear")
                if not code:
                    continue
                obj, created = EmisWarehouseYear.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["years"][0 if created else 1] += 1

            # Subjects
            for item in subjects:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisSubject.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["subjects"][0 if created else 1] += 1

            # Teacher Qualifications
            for item in teacher_quals:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherQual.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["teacher_quals"][0 if created else 1] += 1

            # Marital Status
            for item in marital_statuses:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisMaritalStatus.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["marital_status"][0 if created else 1] += 1

            # Islands
            for item in islands:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisIsland.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["islands"][0 if created else 1] += 1

            # Teacher Statuses
            for item in teacher_statuses:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherStatus.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["teacher_status"][0 if created else 1] += 1

            # Education Levels
            for item in education_levels:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisEducationLevel.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["education_levels"][0 if created else 1] += 1

            # Teacher Link Types
            for item in teacher_link_types:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherLinkType.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["teacher_link_types"][0 if created else 1] += 1

            # Genders
            for item in genders:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisGender.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["genders"][0 if created else 1] += 1

            # Teacher PD Focuses
            for item in pd_focuses:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherPdFocus.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["pd_focuses"][0 if created else 1] += 1

            # Teacher PD Formats
            for item in pd_formats:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherPdFormat.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["pd_formats"][0 if created else 1] += 1

            # Teacher PD Types
            for item in pd_types:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisTeacherPdType.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                counts["pd_types"][0 if created else 1] += 1

        msg = (
            "Schools +{}/{}, "
            "Levels +{}/{}, "
            "Job Titles +{}/{}, "
            "Years +{}/{}, "
            "Subjects +{}/{}, "
            "Qualifications +{}/{}, "
            "Marital Status +{}/{}, "
            "Islands +{}/{}, "
            "Teacher Status +{}/{}, "
            "Education Levels +{}/{}, "
            "Teacher Link Types +{}/{}, "
            "Genders +{}/{}, "
            "PD Focuses +{}/{}, "
            "PD Formats +{}/{}, "
            "PD Types +{}/{}"
        ).format(
            counts["schools"][0],
            counts["schools"][1],
            counts["levels"][0],
            counts["levels"][1],
            counts["job_titles"][0],
            counts["job_titles"][1],
            counts["years"][0],
            counts["years"][1],
            counts["subjects"][0],
            counts["subjects"][1],
            counts["teacher_quals"][0],
            counts["teacher_quals"][1],
            counts["marital_status"][0],
            counts["marital_status"][1],
            counts["islands"][0],
            counts["islands"][1],
            counts["teacher_status"][0],
            counts["teacher_status"][1],
            counts["education_levels"][0],
            counts["education_levels"][1],
            counts["teacher_link_types"][0],
            counts["teacher_link_types"][1],
            counts["genders"][0],
            counts["genders"][1],
            counts["pd_focuses"][0],
            counts["pd_focuses"][1],
            counts["pd_formats"][0],
            counts["pd_formats"][1],
            counts["pd_types"][0],
            counts["pd_types"][1],
        )

        self.stdout.write(self.style.SUCCESS(msg))
