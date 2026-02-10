"""
Management command to expire teacher registrations past their validity date.

Intended to be scheduled (e.g. daily via cron or Windows Task Scheduler):
    python manage.py check_expired_registrations

For each SchoolStaff whose registration_valid_until has passed:
  1. Sets registration_application_status to "expired"
  2. Sets teacher_registration_status FK to the "Expired" EmisTeacherRegistrationStatus
  3. Logs the change in RegistrationChangeLog
  4. Sends an expiry notification email to the teacher
"""

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.emails import send_teacher_registration_expired_email
from core.models import SchoolStaff
from integrations.models import EmisTeacherRegistrationStatus
from teacher_registration import constants
from teacher_registration.models import RegistrationChangeLog


class Command(BaseCommand):
    help = "Expire teacher registrations that are past their validity date"

    def handle(self, *args, **options):
        now = timezone.now()

        # Build renewal URL for email notifications
        try:
            site = Site.objects.get_current()
            domain = site.domain
            if domain.startswith(("http://", "https://")):
                base_url = domain.rstrip("/")
            else:
                base_url = f"https://{domain}"
            renewal_url = f"{base_url}{reverse('teacher_registration:registration_renew')}"
        except Exception:
            renewal_url = None

        # Look up the "Expired" registration status record
        try:
            expired_status = EmisTeacherRegistrationStatus.objects.get(
                label__icontains="expired"
            )
        except EmisTeacherRegistrationStatus.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                "No EmisTeacherRegistrationStatus with 'expired' in its label found. "
                "Please create one in the EMIS lookup data before running this command."
            ))
            return
        except EmisTeacherRegistrationStatus.MultipleObjectsReturned:
            expired_status = EmisTeacherRegistrationStatus.objects.filter(
                label__icontains="expired"
            ).first()

        # Find approved staff whose registration has expired
        expired_qs = SchoolStaff.objects.filter(
            registration_valid_until__isnull=False,
            registration_valid_until__lte=now,
            registration_application_status=constants.APPROVED,
        ).select_related("user", "teacher_registration_status")

        count = 0
        for staff in expired_qs:
            previous_status_label = (
                staff.teacher_registration_status.label if staff.teacher_registration_status else None
            )
            old_app_status = staff.registration_application_status

            # Update the SchoolStaff record
            staff.registration_application_status = constants.EXPIRED
            staff.teacher_registration_status = expired_status
            staff.save(update_fields=[
                "registration_application_status",
                "teacher_registration_status",
                "last_updated_at",
            ])

            # Log the change against the most recent TeacherRegistration
            registration = (
                staff.registration_history
                .order_by("-reviewed_at")
                .first()
            )
            if registration:
                RegistrationChangeLog.log_change(
                    registration=registration,
                    field_name="status",
                    old_value=old_app_status,
                    new_value=constants.EXPIRED,
                    changed_by=None,
                    notes=(
                        f"Registration expired automatically. "
                        f"Valid until: {staff.registration_valid_until:%Y-%m-%d %H:%M}. "
                        f"Previous status: {previous_status_label or 'N/A'}."
                    ),
                )

            # Send notification email
            try:
                send_teacher_registration_expired_email(
                    staff=staff,
                    renewal_url=renewal_url,
                    previous_status_label=previous_status_label,
                )
            except Exception as exc:
                self.stderr.write(self.style.WARNING(
                    f"  Could not send expiry email for {staff.user}: {exc}"
                ))

            count += 1
            self.stdout.write(
                f"  Expired: {staff.user.get_full_name() or staff.user.username} "
                f"(valid until {staff.registration_valid_until:%Y-%m-%d})"
            )

        self.stdout.write(self.style.SUCCESS(f"Expired {count} registration(s)."))
