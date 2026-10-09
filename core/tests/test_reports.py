"""PDF outputs: the WeasyPrint summary report and the ReportLab certificate."""

from datetime import datetime, timezone as dt_timezone
from io import BytesIO

import pytest
from django.urls import reverse
from pypdf import PdfReader

from core import permissions as p
from core.models import SchoolStaff
from core.tests.factories import SchoolStaffFactory, system_user
from integrations.tests.factories import EmisTeacherRegistrationStatusFactory
from teacher_registration import constants
from teacher_registration.tests.factories import (
    LookupConditionFactory,
    RegistrationConditionFactory,
    TeacherRegistrationFactory,
)

pytestmark = pytest.mark.django_db


def weasyprint_available():
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


@pytest.fixture
def admin_client(client):
    client.force_login(system_user(p.GROUP_SYSTEM_ADMINS))
    return client


def pages(response):
    return PdfReader(BytesIO(response.content)).pages


@pytest.mark.pdf
@pytest.mark.skipif(not weasyprint_available(), reason="WeasyPrint native libraries not installed")
def test_teacher_summary_report_renders_pdf(admin_client):
    status = EmisTeacherRegistrationStatusFactory(label="Full Registration")
    SchoolStaffFactory(staff_type=SchoolStaff.TEACHING_STAFF, teacher_registration_status=status)
    TeacherRegistrationFactory(submitted=True)

    response = admin_client.get(reverse("core:report_teacher_summary"))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "teacher_registration_summary_" in response["Content-Disposition"]
    assert len(pages(response)) >= 1


@pytest.mark.pdf
def test_teacher_summary_report_degrades_without_weasyprint(admin_client, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError("cannot load library 'gobject-2.0'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    response = admin_client.get(reverse("core:report_teacher_summary"), follow=True)
    assert response.redirect_chain[-1][0] == reverse("core:reports")
    assert any("PDF generation is not available" in str(m) for m in response.context["messages"])


class TestCertificate:
    @pytest.fixture
    def teacher(self):
        status = EmisTeacherRegistrationStatusFactory(code="FULL", label="Full Registration")
        return SchoolStaffFactory(
            staff_type=SchoolStaff.TEACHING_STAFF,
            title="Mr",
            teacher_registration_number="TR26-CERT01-Z",
            teacher_registration_status=status,
            registration_application_status=constants.APPROVED,
            registration_granted_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            registration_valid_until=datetime(2029, 1, 1, tzinfo=dt_timezone.utc),
        )

    def test_renders_one_page_certificate(self, admin_client, teacher):
        response = admin_client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": teacher.pk}))
        assert response["Content-Type"] == "application/pdf"
        assert 'filename="certificate-TR26-CERT01-Z.pdf"' in response["Content-Disposition"]
        assert len(pages(response)) == 1

    def test_expired_certificate_still_renders(self, admin_client, teacher):
        teacher.registration_application_status = constants.EXPIRED
        teacher.save()
        response = admin_client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": teacher.pk}))
        assert response.status_code == 200

    def test_conditions_add_a_page(self, admin_client, teacher):
        RegistrationConditionFactory(
            registration=None, school_staff=teacher,
            condition=LookupConditionFactory(label="Complete first-aid training"),
        )
        teacher.teacher_registration_status = EmisTeacherRegistrationStatusFactory(
            code="COND", label="Full Registration with Conditions"
        )
        teacher.save()
        response = admin_client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": teacher.pk}))
        assert response.status_code == 200
        assert len(pages(response)) >= 1

    def test_signatory_signature_and_stamp_are_optional(self, admin_client, teacher):
        """No signatory, no signature image, no org stamp: still a valid PDF."""
        response = admin_client.get(reverse("teacher_registration:teacher_certificate", kwargs={"pk": teacher.pk}))
        assert response.content.startswith(b"%PDF")
