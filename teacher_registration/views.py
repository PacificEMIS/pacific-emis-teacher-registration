"""
Views for teacher registration workflow.

This module provides views for:
- Teachers: Create, edit, submit registrations
- Admins: List, review, approve/reject registrations
"""

import re
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery, Prefetch
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core.decorators import require_app_access
from core.models import SchoolStaff, SchoolStaffAssignment
from integrations.models import EmisSchool, EmisClassLevel, EmisSubject
from core.emails import (
    send_new_teacher_registration_email_async,
    send_teacher_registration_submitted_email_async,
    send_teacher_registration_approved_email_async,
    send_teacher_registration_rejected_email_async,
    send_teacher_registration_expired_email,
)
from core.permissions import can_manage_pending_users
from teacher_registration import constants
from teacher_registration.models import (
    TeacherRegistration,
    RegistrationDocument,
    RegistrationCondition,
    RegistrationChangeLog,
    EducationRecord,
    TrainingRecord,
    ClaimedSchoolAppointment,
    ClaimedDuty,
)
from teacher_registration.forms import (
    TeacherRegistrationForm,
    RegistrationDocumentForm,
    RegistrationConditionForm,
    RegistrationReviewForm,
    ChecklistOfficialForm,
    EducationRecordFormSet,
    TrainingRecordFormSet,
    ClaimedSchoolAppointmentFormSet,
    ClaimedDutyFormSet,
)
from integrations.models import EmisTeacherPdType


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

# How far in advance of expiry a teacher can start renewal (3 months)
RENEWAL_WINDOW = timedelta(days=90)

# Required documents checklist with mapping to EMIS document type codes
# Each item: (display_label, list_of_matching_doc_type_codes)
# Multiple codes per item allow for flexible matching (e.g., birth cert OR passport)
# Codes from EmisTeacherLinkType table
REQUIRED_DOCUMENTS = [
    ("Birth Certificate or Passport", ["BIRTHCERT", "PASSPORT"]),
    ("National ID Card", ["NATIONID"]),
    ("Academic Certificate", ["ACACERT"]),
    ("Academic Transcript", ["ACATRANS", "STATERES"]),
    ("Teaching Certificate", ["TEACHCERT", "TEACHINGQUAL"]),
    ("Teaching Transcript", ["TEACHTRANS"]),
    ("Training/Workshop Certificates", ["TRAINCERT"]),
    ("Police Clearance", ["POLCLEAR"]),
    ("Medical Clearance", ["MEDCLEAR"]),
    ("Passport Photo", ["PHOTO", "PORTRAIT"]),
    ("Church Character Reference", ["CHURCHREF"]),
    ("School Leader/Supervisor Reference", ["SCHREF"]),
    ("Registration Fee Receipt", ["REGRECEIPT"]),
]


def get_required_documents_status(documents, staff_documents=None):
    """
    Build a list of required documents with their upload status.

    Args:
        documents: QuerySet of RegistrationDocument objects (on the registration)
        staff_documents: Optional QuerySet of RegistrationDocument objects already
            on the SchoolStaff profile (for renewal forms). Staff documents count
            as uploaded ONLY if their type does not require renewal
            (EmisTeacherLinkType.needs_renewal=False). Documents whose type
            requires renewal must be freshly uploaded.

    Returns:
        List of dicts: [{"label": str, "uploaded": bool}, ...]
    """
    # Get all uploaded document type codes (uppercase for case-insensitive matching)
    uploaded_codes = set()
    for doc in documents:
        if doc.doc_link_type:
            uploaded_codes.add(doc.doc_link_type.code.upper())

    # Also count staff documents already on file (for renewals)
    if staff_documents:
        for doc in staff_documents:
            if doc.doc_link_type:
                uploaded_codes.add(doc.doc_link_type.code.upper())

    # Build status list
    result = []
    for label, codes in REQUIRED_DOCUMENTS:
        # Check if any of the matching codes have been uploaded
        is_uploaded = any(code.upper() in uploaded_codes for code in codes)
        result.append({"label": label, "uploaded": is_uploaded})

    return result


# =============================================================================
# Public views (unauthenticated)
# =============================================================================


def public_landing(request):
    """
    Public landing page for teacher self-registration.

    Shows a welcome message and prompts teachers to sign in to start registration.
    Always shows the landing page regardless of authentication status.
    """
    return render(request, "teacher_registration/public_landing.html", {"hide_sidebar": True})


def public_signout(request):
    """
    Sign out and return to the public landing page.

    Used when someone is signed in but wants to register as a different person.
    Clears any pending messages to avoid showing stale login notifications.
    """
    # Clear any pending messages before logout
    storage = get_messages(request)
    for _ in storage:
        pass
    logout(request)
    return redirect("teacher_registration:public_landing")


def public_start(request):
    """
    Start the public registration process.

    If not logged in, redirects to login with next param.
    If logged in, redirects to my_registration to continue the flow.
    """
    if not request.user.is_authenticated:
        from django.urls import reverse
        from urllib.parse import urlencode

        login_url = reverse("accounts:login")
        next_url = reverse("teacher_registration:my_registration")
        return redirect(f"{login_url}?{urlencode({'next': next_url})}")

    return redirect("teacher_registration:my_registration")


def _page_window(page_obj, radius=2, edges=2):
    """Build a compact pagination window."""
    total = page_obj.paginator.num_pages
    current = page_obj.number
    pages = set()

    for p in range(1, min(edges, total) + 1):
        pages.add(p)
    for p in range(max(1, total - edges + 1), total + 1):
        pages.add(p)

    for p in range(current - radius, current + radius + 1):
        if 1 <= p <= total:
            pages.add(p)

    pages = sorted(pages)
    window = []
    prev = 0
    for p in pages:
        if prev and p != prev + 1:
            window.append("…")
        window.append(p)
        prev = p
    return window


# =============================================================================
# Teacher-facing views (self-registration)
# =============================================================================


@login_required
@never_cache
def my_registration(request):
    """
    Show the teacher's current registration status or start a new one.

    - If admin: redirect to pending registrations list
    - If user has SchoolStaff profile: redirect to dashboard
    - If user has draft registration: redirect to edit it
    - If user has submitted registration: show status
    - Otherwise: redirect to create a new registration
    """
    user = request.user

    # If admin, redirect to pending registrations list
    if can_manage_pending_users(user):
        return redirect("teacher_registration:pending_list")

    # Check for existing registrations (prefetch change logs for history display)
    registrations = (
        TeacherRegistration.objects.filter(user=user)
        .prefetch_related("change_logs__changed_by")
        .order_by("-created_at")
    )

    # Check if user already has a SchoolStaff profile (approved teacher)
    if hasattr(user, "school_staff"):
        staff = user.school_staff
        is_approved = staff.registration_application_status == constants.APPROVED
        is_expired = staff.registration_application_status == constants.EXPIRED

        # Check for in-progress renewal registration
        renewal_in_progress = registrations.filter(
            registration_type=TeacherRegistration.RENEWAL,
            status__in=[constants.DRAFT, constants.SUBMITTED, constants.UNDER_REVIEW],
        ).first()

        # If there's a draft renewal, redirect to edit it
        if renewal_in_progress and renewal_in_progress.status == constants.DRAFT:
            return redirect("teacher_registration:edit", pk=renewal_in_progress.pk)

        # Can renew: expired, or approaching expiry (within 3 months)
        can_renew = is_expired or (
            is_approved
            and staff.registration_valid_until
            and staff.registration_valid_until <= timezone.now() + RENEWAL_WINDOW
        )

        return render(
            request,
            "teacher_registration/my_registration.html",
            {
                "active": "my_registration",
                "registrations": registrations,
                "is_approved": is_approved,
                "is_expired": is_expired,
                "renewal_in_progress": renewal_in_progress,
                "can_renew": can_renew,
                "staff": staff,
            },
        )

    # If has draft, go to edit
    draft = registrations.filter(status=constants.DRAFT).first()
    if draft:
        return redirect("teacher_registration:edit", pk=draft.pk)

    # If no registrations at all, redirect to create one
    if not registrations.exists():
        return redirect("teacher_registration:create")

    # Show status page for submitted/pending/rejected registrations
    return render(
        request,
        "teacher_registration/my_registration.html",
        {
            "active": "my_registration",
            "registrations": registrations,
        },
    )


@login_required
def registration_create(request):
    """
    Start a new teacher registration.

    Creates a draft registration and redirects to edit form.
    """
    user = request.user

    # Check if user already has a SchoolStaff profile
    if hasattr(user, "school_staff"):
        messages.info(request, "You are already registered as school staff.")
        return redirect("dashboard")

    # Check for existing draft
    existing_draft = TeacherRegistration.objects.filter(
        user=user, status=constants.DRAFT
    ).first()

    if existing_draft:
        return redirect("teacher_registration:edit", pk=existing_draft.pk)

    # Check for pending registration
    pending = TeacherRegistration.objects.filter(
        user=user, status__in=[constants.SUBMITTED, constants.UNDER_REVIEW]
    ).first()

    if pending:
        messages.warning(
            request,
            "You already have a registration pending review. Please wait for it to be processed.",
        )
        return redirect("teacher_registration:my_registration")

    # Create new draft registration
    registration = TeacherRegistration.objects.create(
        user=user,
        registration_type=TeacherRegistration.INITIAL,
        status=constants.DRAFT,
        created_by=user,
        last_updated_by=user,
    )

    # Log registration creation
    RegistrationChangeLog.log_change(
        registration=registration,
        field_name="status",
        old_value="",
        new_value=constants.DRAFT,
        changed_by=user,
        notes="Registration created (self-registration)",
    )

    # Send email notification to admins about new registration
    from django.urls import reverse

    pending_registrations_url = request.build_absolute_uri(
        reverse("teacher_registration:pending_list")
    )
    send_new_teacher_registration_email_async(
        registration=registration,
        pending_registrations_url=pending_registrations_url,
    )

    messages.success(request, "Registration started. Please fill out the form below.")
    return redirect("teacher_registration:edit", pk=registration.pk)


@login_required
@never_cache
def registration_edit(request, pk):
    """
    Edit a draft registration.

    - Owner can edit their own registration
    - Admins can edit any registration
    Save Draft: saves without validation
    Save & Submit: validates required fields before submitting
    """
    registration = get_object_or_404(TeacherRegistration, pk=pk)
    is_renewal = registration.registration_type == TeacherRegistration.RENEWAL

    # Check permissions: owner or admin
    is_owner = registration.user == request.user
    is_admin = can_manage_pending_users(request.user)

    if not is_owner and not is_admin:
        raise PermissionDenied("You can only edit your own registration.")

    # Check status
    if not registration.is_editable:
        messages.error(request, "This registration can no longer be edited.")
        if is_admin:
            return redirect("teacher_registration:pending_list")
        return redirect("teacher_registration:my_registration")

    if request.method == "POST":
        form = TeacherRegistrationForm(request.POST, instance=registration)
        education_formset = EducationRecordFormSet(request.POST, instance=registration, prefix="education_records")
        training_formset = TrainingRecordFormSet(request.POST, instance=registration, prefix="training_records")
        appointment_formset = ClaimedSchoolAppointmentFormSet(request.POST, instance=registration, prefix="claimed_appointments")
        is_submitting = "submit" in request.POST

        # Check all forms are valid
        form_valid = form.is_valid()
        education_valid = education_formset.is_valid()
        training_valid = training_formset.is_valid()
        appointment_valid = appointment_formset.is_valid()

        if form_valid and education_valid and training_valid and appointment_valid:
            # If submitting, validate required fields
            if is_submitting:
                errors = []
                first_name = form.cleaned_data.get("first_name", "").strip()
                last_name = form.cleaned_data.get("last_name", "").strip()

                if not first_name:
                    errors.append("First name is required.")
                if not last_name:
                    errors.append("Last name is required.")

                if errors:
                    for error in errors:
                        messages.error(request, error)
                    # Re-render the form with errors
                    documents = registration.documents.all()
                    staff_documents = None
                    if registration.registration_type == TeacherRegistration.RENEWAL and registration.approved_staff_profile:
                        staff_documents = RegistrationDocument.objects.filter(
                            school_staff=registration.approved_staff_profile
                        ).select_related("doc_link_type")
                    required_docs_status = get_required_documents_status(documents, staff_documents)
                    return render(
                        request,
                        "teacher_registration/registration_form.html",
                        {
                            "form": form,
                            "education_formset": education_formset,
                            "training_formset": training_formset,
                            "appointment_formset": appointment_formset,
                            "registration": registration,
                            "documents": documents,
                            "staff_documents": staff_documents,
                            "document_form": RegistrationDocumentForm(),
                            "is_admin": is_admin,
                            "required_docs_status": required_docs_status,
                            "checklist_items": constants.CHECKLIST_ITEMS,
                            "is_renewal": is_renewal,
                        },
                    )

            # Save the registration
            registration = form.save(commit=False)
            registration.last_updated_by = request.user
            registration.save()

            # Save the formsets
            education_formset.instance = registration
            education_formset.save()
            training_formset.instance = registration
            training_formset.save()
            appointment_formset.instance = registration
            appointment_formset.save()

            # Also save the user's name
            first_name = form.cleaned_data.get("first_name", "")
            last_name = form.cleaned_data.get("last_name", "")
            registration.user.first_name = first_name
            registration.user.last_name = last_name
            registration.user.save(update_fields=["first_name", "last_name"])
            messages.success(request, "Registration saved.")

            # If submitting, submit and redirect appropriately
            if is_submitting:
                registration.submit(user=request.user)

                # Send email notification to admins about submitted registration
                from django.urls import reverse

                review_url = request.build_absolute_uri(
                    reverse("teacher_registration:review", kwargs={"pk": registration.pk})
                )
                send_teacher_registration_submitted_email_async(
                    registration=registration,
                    review_url=review_url,
                )

                messages.success(request, "Registration submitted for review.")
                if is_admin:
                    return redirect("teacher_registration:pending_list")
                return redirect("teacher_registration:my_registration")

            return redirect("teacher_registration:edit", pk=registration.pk)
        else:
            # Forms are invalid - show errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            # Show formset errors
            for formset, name in [
                (education_formset, "Education"),
                (training_formset, "Training"),
                (appointment_formset, "Appointment"),
            ]:
                for form_errors in formset.errors:
                    for field, errors in form_errors.items():
                        for error in errors:
                            messages.error(request, f"{name} - {field}: {error}")
    else:
        form = TeacherRegistrationForm(instance=registration, user=registration.user)
        education_formset = EducationRecordFormSet(instance=registration, prefix="education_records")
        training_formset = TrainingRecordFormSet(instance=registration, prefix="training_records")
        appointment_formset = ClaimedSchoolAppointmentFormSet(instance=registration, prefix="claimed_appointments")

    # Get documents for this registration
    documents = registration.documents.all()

    # For renewals, also fetch existing documents on the SchoolStaff profile
    # (only the most recent per document type to avoid duplicates from prior renewals)
    staff_documents = None
    if registration.registration_type == TeacherRegistration.RENEWAL and registration.approved_staff_profile:
        staff_docs_qs = RegistrationDocument.objects.filter(
            school_staff=registration.approved_staff_profile
        ).select_related("doc_link_type").order_by("doc_link_type_id", "-created_at")
        seen_types = set()
        staff_documents = []
        for doc in staff_docs_qs:
            if doc.doc_link_type_id not in seen_types:
                seen_types.add(doc.doc_link_type_id)
                staff_documents.append(doc)

    # Get PD types for training title autocomplete
    pd_types = EmisTeacherPdType.objects.filter(active=True).order_by("label")

    # Build required documents status for checklist
    required_docs_status = get_required_documents_status(documents, staff_documents)

    return render(
        request,
        "teacher_registration/registration_form.html",
        {
            "form": form,
            "education_formset": education_formset,
            "training_formset": training_formset,
            "appointment_formset": appointment_formset,
            "registration": registration,
            "documents": documents,
            "staff_documents": staff_documents,
            "document_form": RegistrationDocumentForm(),
            "is_admin": is_admin,
            "pd_types": pd_types,
            "required_docs_status": required_docs_status,
            "checklist_items": constants.CHECKLIST_ITEMS,
            "is_renewal": is_renewal,
        },
    )


@login_required
def registration_submit(request, pk):
    """
    Submit a draft registration for review.
    """
    registration = get_object_or_404(TeacherRegistration, pk=pk)

    # Check ownership
    if registration.user != request.user:
        raise PermissionDenied("You can only submit your own registration.")

    # Check status
    if registration.status != constants.DRAFT:
        messages.error(request, "This registration has already been submitted.")
        return redirect("teacher_registration:my_registration")

    if request.method == "POST":
        registration.submit(user=request.user)

        # Send email notification to admins about submitted registration
        from django.urls import reverse

        review_url = request.build_absolute_uri(
            reverse("teacher_registration:review", kwargs={"pk": registration.pk})
        )
        send_teacher_registration_submitted_email_async(
            registration=registration,
            review_url=review_url,
        )

        messages.success(
            request,
            "Your registration has been submitted for review. You will be notified when it is processed.",
        )
        return redirect("teacher_registration:my_registration")

    # Show confirmation page
    return render(
        request,
        "teacher_registration/registration_submit.html",
        {
            "registration": registration,
        },
    )


@login_required
def document_upload(request, registration_pk):
    """
    Upload a document to a registration.
    """
    registration = get_object_or_404(TeacherRegistration, pk=registration_pk)

    # Check ownership (allow admins to upload for any registration)
    is_owner = registration.user == request.user
    is_admin = can_manage_pending_users(request.user)
    if not is_owner and not is_admin:
        raise PermissionDenied("You can only upload documents to your own registration.")

    # Check status
    if not registration.is_editable:
        messages.error(request, "Documents cannot be added to this registration.")
        return redirect("teacher_registration:edit", pk=registration.pk)

    if request.method == "POST":
        form = RegistrationDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.registration = registration
            document.created_by = request.user
            document.last_updated_by = request.user
            document.save()
            messages.success(request, "Document uploaded successfully.")
        else:
            for error in form.errors.values():
                messages.error(request, error)

    # Redirect back to edit page
    return redirect("teacher_registration:edit", pk=registration.pk)


@login_required
def document_delete(request, registration_pk, pk):
    """
    Delete a document from a registration.
    """
    registration = get_object_or_404(TeacherRegistration, pk=registration_pk)
    document = get_object_or_404(RegistrationDocument, pk=pk, registration=registration)

    # Check ownership (allow admins to delete for any registration)
    is_owner = registration.user == request.user
    is_admin = can_manage_pending_users(request.user)
    if not is_owner and not is_admin:
        raise PermissionDenied("You can only delete documents from your own registration.")

    # Check status
    if not registration.is_editable:
        messages.error(request, "Documents cannot be removed from this registration.")
        return redirect("teacher_registration:edit", pk=registration.pk)

    if request.method == "POST":
        document.delete()
        messages.success(request, "Document deleted.")

    # Redirect back to edit page
    return redirect("teacher_registration:edit", pk=registration.pk)


# =============================================================================
# Admin-facing views (review workflow)
# =============================================================================


@login_required
@require_app_access
@never_cache
def pending_registrations_list(request):
    """
    List all pending teacher registrations for admin review.

    Includes drafts (in progress), submitted, and under review registrations.
    Accessible to users who can manage pending users (Admins, System Admins).
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Base queryset - include drafts, submitted, under review, ready for approval, and rejected
    registrations_qs = TeacherRegistration.objects.filter(
        status__in=[
            constants.DRAFT,
            constants.SUBMITTED,
            constants.UNDER_REVIEW,
            constants.READY_FOR_APPROVAL,
            constants.REJECTED,
        ]
    ).select_related("user", "preferred_school", "reviewed_by")  # preferred_school: not currently in use

    # Apply status filter
    if status_filter:
        registrations_qs = registrations_qs.filter(status=status_filter)

    # Search by name or email
    if q:
        registrations_qs = registrations_qs.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__email__icontains=q)
        )

    # Order: under_review/submitted first, then rejected, then drafts
    from django.db.models import Case, When, Value, IntegerField

    registrations_qs = registrations_qs.annotate(
        status_order=Case(
            When(status=constants.READY_FOR_APPROVAL, then=Value(0)),
            When(status=constants.UNDER_REVIEW, then=Value(1)),
            When(status=constants.SUBMITTED, then=Value(2)),
            When(status=constants.REJECTED, then=Value(3)),
            When(status=constants.DRAFT, then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by("status_order", "-created_at")

    # Pagination
    paginator = Paginator(registrations_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "teacher_registration/pending_list.html",
        {
            "active": "pending_registrations",
            "page_obj": page_obj,
            "q": q,
            "status_filter": status_filter,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
        },
    )


@login_required
@require_app_access
@never_cache
def registration_review(request, pk):
    """
    Review a teacher registration (approve or reject).
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    registration = get_object_or_404(
        TeacherRegistration.objects.select_related(
            "user", "preferred_school", "preferred_job_title", "reviewed_by",  # preferred_school/preferred_job_title: not currently in use
            "approved_staff_profile",
        ).prefetch_related("documents__doc_link_type"),
        pk=pk,
    )

    # Check if registration can be reviewed
    if registration.status not in [
        constants.SUBMITTED,
        constants.UNDER_REVIEW,
        constants.READY_FOR_APPROVAL,
        constants.REJECTED,
    ]:
        messages.error(request, "This registration cannot be reviewed.")
        return redirect("teacher_registration:pending_list")

    # Mark as under review if not already (allows re-review of rejected registrations)
    if registration.status in [constants.SUBMITTED, constants.REJECTED]:
        registration.start_review(request.user)

    is_renewal = registration.registration_type == TeacherRegistration.RENEWAL

    if request.method == "POST":
        submit_action = request.POST.get("submit_action", "decision")
        checklist_form = ChecklistOfficialForm(request.POST, instance=registration)

        # Always save the checklist regardless of review form validity
        if checklist_form.is_valid():
            checklist_form.save()

        if submit_action == "save":
            # Save checklist only — handle ready-for-approval transitions
            registration.refresh_from_db()
            if registration.checklist_ready_for_approval and registration.status == constants.UNDER_REVIEW:
                registration.mark_ready_for_approval(request.user)
                messages.success(request, "Checklist saved. Registration marked as ready for approval.")
            elif not registration.checklist_ready_for_approval and registration.status == constants.READY_FOR_APPROVAL:
                registration.revert_to_under_review(request.user)
                messages.success(request, "Checklist saved. Ready for Approval status removed.")
            else:
                messages.success(request, "Checklist saved.")
            return redirect("teacher_registration:review", pk=registration.pk)

        form = RegistrationReviewForm(request.POST)

        if form.is_valid():
            action = form.cleaned_data["action"]
            comments = form.cleaned_data["comments"]

            if action == RegistrationReviewForm.ACTION_APPROVE:
                try:
                    registration_status = form.cleaned_data.get("teacher_registration_status")
                    staff = registration.approve(
                        reviewer=request.user,
                        comments=comments,
                        registration_status=registration_status,
                    )

                    # Send approval email to the teacher
                    from django.urls import reverse

                    my_registration_url = request.build_absolute_uri(
                        reverse("teacher_registration:my_registration")
                    )
                    send_teacher_registration_approved_email_async(
                        registration=registration,
                        dashboard_url=my_registration_url,
                    )

                    if is_renewal:
                        msg = (
                            f"Renewal approved. {registration.user.get_full_name()}'s registration has been renewed. "
                            f"Registration Number: {staff.teacher_registration_number}"
                        )
                    else:
                        msg = (
                            f"Registration approved. {registration.user.get_full_name()} is now a registered teacher. "
                            f"Registration Number: {staff.teacher_registration_number}"
                        )
                    messages.success(
                        request,
                        msg,
                    )
                    return redirect("teacher_registration:teacher_detail", pk=staff.pk)

                except ValidationError as e:
                    # Handle validation errors (e.g., duplicate National ID, missing fields)
                    # Extract error message from ValidationError
                    if hasattr(e, 'message'):
                        error_message = e.message
                    elif hasattr(e, 'messages') and e.messages:
                        error_message = ' '.join(str(msg) for msg in e.messages)
                    else:
                        error_message = str(e)

                    messages.error(request, f"Cannot approve registration: {error_message}")
                    # Stay on review page to allow correction

            elif action == RegistrationReviewForm.ACTION_REJECT:
                registration.reject(reviewer=request.user, comments=comments)

                # Send rejection email to the teacher
                from django.urls import reverse

                my_registration_url = request.build_absolute_uri(
                    reverse("teacher_registration:my_registration")
                )
                send_teacher_registration_rejected_email_async(
                    registration=registration,
                    rejection_reason=comments,
                    my_registration_url=my_registration_url,
                )

                messages.success(request, "Registration rejected. The teacher has been notified by email.")
                return redirect("teacher_registration:pending_list")
    else:
        form = RegistrationReviewForm()
        checklist_form = ChecklistOfficialForm(instance=registration)

    # For renewals, fetch the staff's existing documents so the reviewer
    # can see what is already on file and which types have been re-submitted.
    staff_documents = None
    if is_renewal and registration.approved_staff_profile_id:
        renewed_type_codes = {
            doc.doc_link_type.code.upper()
            for doc in registration.documents.all()
            if doc.doc_link_type_id
        }
        staff_docs_qs = RegistrationDocument.objects.filter(
            school_staff=registration.approved_staff_profile,
        ).select_related("doc_link_type").order_by("doc_link_type_id", "-created_at")
        seen_types = set()
        staff_documents = []
        for doc in staff_docs_qs:
            if doc.doc_link_type_id in seen_types:
                continue
            seen_types.add(doc.doc_link_type_id)
            staff_documents.append({
                "doc": doc,
                "needs_renewal": doc.doc_link_type.needs_renewal if doc.doc_link_type else False,
                "renewed": (
                    doc.doc_link_type.needs_renewal
                    and doc.doc_link_type.code.upper() in renewed_type_codes
                ) if doc.doc_link_type else False,
            })

    condition_form = RegistrationConditionForm()

    return render(
        request,
        "teacher_registration/registration_review.html",
        {
            "active": "pending_registrations",
            "registration": registration,
            "form": form,
            "checklist_form": checklist_form,
            "checklist_items": constants.CHECKLIST_ITEMS,
            "is_renewal": is_renewal,
            "staff_documents": staff_documents,
            "condition_form": condition_form,
            "conditions": registration.conditions.select_related("condition").all(),
        },
    )


@login_required
@require_app_access
def condition_add(request, pk):
    """Add a condition to a registration during review."""
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    registration = get_object_or_404(TeacherRegistration, pk=pk)

    if registration.status not in [
        constants.UNDER_REVIEW,
        constants.READY_FOR_APPROVAL,
    ]:
        return JsonResponse({"error": "Conditions can only be added during review."}, status=400)

    if request.method == "POST":
        form = RegistrationConditionForm(request.POST)
        if form.is_valid():
            condition = form.save(commit=False)
            condition.registration = registration
            condition.created_by = request.user
            condition.last_updated_by = request.user
            condition.save()
            return JsonResponse({
                "id": condition.pk,
                "label": condition.condition.label,
                "notes": condition.notes,
            })
        return JsonResponse({"error": form.errors}, status=400)

    return JsonResponse({"error": "POST required."}, status=405)


@login_required
@require_app_access
def condition_remove(request, pk):
    """Remove a condition from a registration during review."""
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    condition = get_object_or_404(RegistrationCondition, pk=pk, registration__isnull=False)

    if condition.registration.status not in [
        constants.UNDER_REVIEW,
        constants.READY_FOR_APPROVAL,
    ]:
        return JsonResponse({"error": "Conditions can only be removed during review."}, status=400)

    if request.method == "POST":
        condition.delete()
        return JsonResponse({"success": True})

    return JsonResponse({"error": "POST required."}, status=405)


@login_required
@require_app_access
def registration_history(request):
    """
    View all registrations (including approved/rejected) for audit purposes.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    registrations_qs = TeacherRegistration.objects.select_related(
        "user", "preferred_school", "reviewed_by", "approved_staff_profile"  # preferred_school: not currently in use
    )

    # Apply status filter
    if status_filter:
        registrations_qs = registrations_qs.filter(status=status_filter)

    # Search by name or email
    if q:
        registrations_qs = registrations_qs.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__email__icontains=q)
        )

    registrations_qs = registrations_qs.order_by("-created_at")

    # Pagination
    paginator = Paginator(registrations_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "teacher_registration/registration_history.html",
        {
            "active": "pending_registrations",
            "page_obj": page_obj,
            "q": q,
            "status_filter": status_filter,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            "status_choices": constants.REGISTRATION_APPLICATION_STATUS_CHOICES,
        },
    )


@login_required
@require_app_access
def registration_delete(request, pk):
    """
    Delete a teacher registration.

    For testing purposes, allows admins to delete any registration.
    The Django user account is NOT deleted - they become a pending user
    (unless they have another profile like SchoolStaff).
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    registration = get_object_or_404(
        TeacherRegistration.objects.select_related("user"),
        pk=pk,
    )

    if request.method == "POST":
        user = registration.user
        full_name = user.get_full_name() or user.username
        registration.delete()
        messages.success(
            request,
            f"Registration for '{full_name}' has been deleted.",
        )
        return redirect("teacher_registration:pending_list")

    return render(
        request,
        "teacher_registration/registration_delete.html",
        {
            "active": "pending_registrations",
            "registration": registration,
        },
    )


# =============================================================================
# Teachers views (Teaching Staff from SchoolStaff model)
# =============================================================================


@login_required
@require_app_access
def teachers_list(request):
    """
    List all teachers (SchoolStaff with staff_type=TEACHING_STAFF).

    This is a purpose-built view for the teacher registration application that
    filters SchoolStaff to show only teaching staff (teachers).
    """
    q = (request.GET.get("q") or "").strip()

    # Filters
    school_filter = (request.GET.get("school") or "").strip()
    registration_application_status_filter = (request.GET.get("registration_application_status") or "").strip()

    # Sorting
    sort = (request.GET.get("sort") or "").strip().lower()
    dir_ = (request.GET.get("dir") or "asc").strip().lower()
    dir_ = "desc" if dir_ == "desc" else "asc"

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Picklists
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_name")

    # Latest assignment subqueries (for current school display)
    assignment_qs = SchoolStaffAssignment.objects.filter(
        school_staff=OuterRef("pk")
    ).order_by("-id")

    latest_school_no = Subquery(assignment_qs.values("school__emis_school_no")[:1])
    latest_school_name = Subquery(assignment_qs.values("school__emis_school_name")[:1])

    # Base queryset - ONLY teaching staff
    teachers_qs = (
        SchoolStaff.objects.filter(staff_type=SchoolStaff.TEACHING_STAFF)
        .select_related("user")
        .annotate(
            latest_school_no=latest_school_no,
            latest_school_name=latest_school_name,
        )
        .prefetch_related(
            Prefetch(
                "assignments",
                queryset=SchoolStaffAssignment.objects.select_related(
                    "school", "job_title"
                ),
            ),
            "user__groups",
        )
    )

    # Search by name
    if q:
        teachers_qs = teachers_qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )

    # Filter by school (any assignment at that school)
    if school_filter:
        teachers_qs = teachers_qs.filter(
            assignments__school__emis_school_no=school_filter
        ).distinct()

    # Filter by registration application status
    if registration_application_status_filter:
        teachers_qs = teachers_qs.filter(registration_application_status=registration_application_status_filter)

    # Sorting map
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "school": (
            "latest_school_name",
            "user__last_name",
            "user__first_name",
        ),
        "status": (
            "registration_application_status",
            "user__last_name",
            "user__first_name",
        ),
    }

    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        teachers_qs = teachers_qs.order_by(*order_fields)
    else:
        # Default ordering by name
        teachers_qs = teachers_qs.order_by("user__last_name", "user__first_name")

    # Pagination
    paginator = Paginator(teachers_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Only Admins and System Admins can delete teachers
    can_delete = can_manage_pending_users(request.user)

    return render(
        request,
        "teacher_registration/teachers_list.html",
        {
            "active": "teachers",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            # Filters
            "school": school_filter,
            "registration_application_status": registration_application_status_filter,
            "schools": schools,
            "registration_application_status_choices": constants.REGISTRATION_APPLICATION_STATUS_CHOICES,
            # Sorting
            "sort": sort,
            "dir": dir_,
            # Permissions
            "can_delete": can_delete,
        },
    )


@login_required
@require_app_access
def teacher_detail(request, pk):
    """
    View details of a teacher (SchoolStaff with staff_type=TEACHING_STAFF).

    Shows teacher profile, current assignments, and registration history.
    """
    teacher = get_object_or_404(
        SchoolStaff.objects.filter(staff_type=SchoolStaff.TEACHING_STAFF)
        .select_related("user")
        .prefetch_related(
            "assignments__school",
            "assignments__job_title",
            "documents__doc_link_type",
            "registration_history__change_logs",
            "conditions__condition",
            "education_records__qualification",
            "education_records__major",
            "education_records__minor",
            "training_records__focus",
            "training_records__format",
        ),
        pk=pk,
    )

    # Get active assignments with teaching duties
    active_assignments = teacher.active_assignments.select_related(
        "school", "job_title"
    ).prefetch_related(
        "teaching_duties__year_level",
        "teaching_duties__subject",
    )

    # Get registration history (if this teacher was created via registration)
    registration_history = teacher.registration_history.all()

    # Only Admins and System Admins can delete teachers
    can_delete = can_manage_pending_users(request.user)

    return render(
        request,
        "teacher_registration/teacher_detail.html",
        {
            "active": "teachers",
            "teacher": teacher,
            "active_assignments": active_assignments,
            "registration_history": registration_history,
            "can_delete": can_delete,
        },
    )


@login_required
@require_app_access
def teacher_delete(request, pk):
    """
    Delete a teacher (SchoolStaff record).

    This removes the SchoolStaff profile but keeps:
    - The Django user account (becomes a pending user)
    - Any TeacherRegistration records (for audit trail)

    The registration's approved_staff_profile link will be cleared.
    Admins can then clean up via Pending Registrations and Pending Users.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    teacher = get_object_or_404(
        SchoolStaff.objects.filter(staff_type=SchoolStaff.TEACHING_STAFF)
        .select_related("user"),
        pk=pk,
    )

    if request.method == "POST":
        user = teacher.user
        full_name = user.get_full_name() or user.username

        # Clear the approved_staff_profile link on any registrations
        # so the registration history is preserved but no longer linked
        TeacherRegistration.objects.filter(approved_staff_profile=teacher).update(
            approved_staff_profile=None
        )

        # Delete the SchoolStaff record (cascades to assignments, documents)
        teacher.delete()

        messages.success(
            request,
            f"Teacher '{full_name}' has been deleted. The user account remains as a pending user.",
        )
        return redirect("teacher_registration:teachers_list")

    return render(
        request,
        "teacher_registration/teacher_delete.html",
        {
            "active": "teachers",
            "teacher": teacher,
        },
    )


@login_required
@require_app_access
def teacher_resend_renewal_notification(request, pk):
    """Resend the registration-expired / renewal notification email to a teacher."""
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    if request.method != "POST":
        return redirect("teacher_registration:teacher_detail", pk=pk)

    teacher = get_object_or_404(
        SchoolStaff.objects.filter(staff_type=SchoolStaff.TEACHING_STAFF)
        .select_related("user", "teacher_registration_status"),
        pk=pk,
    )

    previous_status_label = (
        teacher.teacher_registration_status.label
        if teacher.teacher_registration_status
        else None
    )

    renewal_url = request.build_absolute_uri(
        reverse("teacher_registration:registration_renew")
    )

    try:
        send_teacher_registration_expired_email(
            staff=teacher,
            renewal_url=renewal_url,
            previous_status_label=previous_status_label,
        )
        msg = "Renewal notification email has been resent."
        ok = True
    except Exception:
        msg = "Failed to send the renewal notification email."
        ok = False

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": ok, "message": msg})

    messages.success(request, msg) if ok else messages.error(request, msg)
    return redirect("teacher_registration:teacher_detail", pk=pk)


# =============================================================================
# Renewal
# =============================================================================


@login_required
def registration_renew(request):
    """
    Start a renewal registration for an expired (or soon-to-expire) teacher.

    Creates a new TeacherRegistration with registration_type=RENEWAL,
    pre-filled from the teacher's existing SchoolStaff data, then
    redirects to the edit form.

    Eligibility:
    - SchoolStaff.registration_application_status == EXPIRED, or
    - SchoolStaff.registration_application_status == APPROVED and
      registration_valid_until is within RENEWAL_WINDOW (3 months)
    """
    user = request.user

    # Guard: user must have a SchoolStaff profile
    if not hasattr(user, "school_staff"):
        messages.error(request, "You do not have a staff profile.")
        return redirect("teacher_registration:my_registration")

    staff = user.school_staff
    is_expired = staff.registration_application_status == constants.EXPIRED
    is_approaching_expiry = (
        staff.registration_application_status == constants.APPROVED
        and staff.registration_valid_until
        and staff.registration_valid_until <= timezone.now() + RENEWAL_WINDOW
    )

    if not is_expired and not is_approaching_expiry:
        messages.info(request, "Your registration is not yet eligible for renewal.")
        return redirect("teacher_registration:my_registration")

    # Guard: no existing in-progress renewal
    existing = TeacherRegistration.objects.filter(
        user=user,
        registration_type=TeacherRegistration.RENEWAL,
        status__in=[constants.DRAFT, constants.SUBMITTED, constants.UNDER_REVIEW],
    ).first()

    if existing:
        if existing.status == constants.DRAFT:
            return redirect("teacher_registration:edit", pk=existing.pk)
        messages.info(request, "You already have a renewal pending review.")
        return redirect("teacher_registration:my_registration")

    # Create the renewal registration pre-filled from SchoolStaff
    registration = TeacherRegistration.objects.create(
        user=user,
        registration_type=TeacherRegistration.RENEWAL,
        teacher_category=TeacherRegistration.CURRENT_TEACHER,
        status=constants.DRAFT,
        approved_staff_profile=staff,
        # Personal information
        title=staff.title,
        date_of_birth=staff.date_of_birth,
        gender=staff.gender,
        marital_status=staff.marital_status,
        nationality=staff.nationality,
        national_id_number=staff.national_id_number,
        home_island=staff.home_island,
        # Contact information
        phone_number=staff.phone_number,
        phone_home=staff.phone_home,
        # Residential address
        residential_address=staff.residential_address,
        nearby_school=staff.nearby_school,
        # Business address
        business_address=staff.business_address,
        # Professional information
        teacher_payroll_number=staff.teacher_payroll_number,
        highest_qualification=staff.highest_qualification,
        years_of_experience=staff.years_of_experience,
        # Audit
        created_by=user,
        last_updated_by=user,
    )

    # Copy education records from StaffEducationRecord → EducationRecord
    for edu in staff.education_records.all():
        EducationRecord.objects.create(
            registration=registration,
            institution_name=edu.institution_name,
            qualification=edu.qualification,
            program_name=edu.program_name,
            major=edu.major,
            minor=edu.minor,
            completion_year=edu.completion_year,
            duration=edu.duration,
            duration_unit=edu.duration_unit,
            completed=edu.completed,
            percentage_progress=edu.percentage_progress,
            comment=edu.comment,
            created_by=user,
            last_updated_by=user,
        )

    # Copy training records from StaffTrainingRecord → TrainingRecord
    for training in staff.training_records.all():
        TrainingRecord.objects.create(
            registration=registration,
            provider_institution=training.provider_institution,
            title=training.title,
            focus=training.focus,
            format=training.format,
            completion_year=training.completion_year,
            duration=training.duration,
            duration_unit=training.duration_unit,
            effective_date=training.effective_date,
            expiration_date=training.expiration_date,
            created_by=user,
            last_updated_by=user,
        )

    # Copy assignments from SchoolStaffAssignment → ClaimedSchoolAppointment + ClaimedDuty
    for assignment in staff.assignments.all():
        appointment = ClaimedSchoolAppointment.objects.create(
            registration=registration,
            current_school=assignment.school,
            employment_position=assignment.job_title,
            teacher_level_type=assignment.teacher_level_type,
            start_date=assignment.start_date,
            end_date=assignment.end_date,
            # Optional fields left blank: current_island_station, years_of_experience,
            # employment_status, class_type (not stored on SchoolStaffAssignment)
            created_by=user,
            last_updated_by=user,
        )

        for duty in assignment.teaching_duties.all():
            ClaimedDuty.objects.create(
                appointment=appointment,
                year_level=duty.year_level,
                subject=duty.subject,
                created_by=user,
                last_updated_by=user,
            )

    # Documents: do NOT copy. Existing docs stay on SchoolStaff.
    # They will be shown as "already on file" on the renewal form.

    # Log creation
    RegistrationChangeLog.log_change(
        registration=registration,
        field_name="status",
        old_value="",
        new_value=constants.DRAFT,
        changed_by=user,
        notes="Renewal registration created (pre-filled from staff profile)",
    )

    # Send admin notification email
    pending_registrations_url = request.build_absolute_uri(
        reverse("teacher_registration:pending_list")
    )
    send_new_teacher_registration_email_async(
        registration=registration,
        pending_registrations_url=pending_registrations_url,
    )

    messages.success(
        request,
        "Renewal started. Your information has been pre-filled. "
        "Please review and update as needed.",
    )
    return redirect("teacher_registration:edit", pk=registration.pk)


# =============================================================================
# Claimed Duties Management (Modal)
# =============================================================================


@login_required
@never_cache
def manage_claimed_duties(request, appointment_id):
    """
    Manage claimed duties for a school appointment (modal view).

    GET: Returns HTML for grouped duty form to render in modal
    POST: Saves duties (expanding grouped entries into individual records) and returns JSON response

    Permissions:
    - User must own the registration
    - Registration must be editable (DRAFT status)
    """
    appointment = get_object_or_404(
        ClaimedSchoolAppointment.objects.select_related("registration"),
        pk=appointment_id
    )
    registration = appointment.registration

    # Check permissions: owner or admin
    is_owner = registration.user == request.user
    is_admin = can_manage_pending_users(request.user)

    if not is_owner and not is_admin:
        if request.method == "POST":
            return JsonResponse(
                {"success": False, "error": "Permission denied"},
                status=403
            )
        raise PermissionDenied("You can only manage your own registration.")

    # Check if registration is editable
    if not registration.is_editable:
        if request.method == "POST":
            return JsonResponse(
                {"success": False, "error": "Registration is no longer editable"},
                status=400
            )
        messages.error(request, "This registration can no longer be edited.")
        return redirect("teacher_registration:edit", pk=registration.pk)

    if request.method == "POST":
        # Parse grouped duty data from POST
        # Format: duties[0][year_level], duties[0][subjects][], duties[1][year_level], etc.
        try:
            # Get all existing duties to track what needs deletion
            existing_duties = list(appointment.claimed_duties.all())
            existing_duty_ids = {duty.pk for duty in existing_duties}
            duties_to_keep = set()

            # Parse the grouped duties from the form
            # Discover all duty indices from POST keys (handles gaps)
            duty_indices = sorted({
                int(m.group(1))
                for key in request.POST
                if (m := re.match(r"duties\[(\d+)\]\[year_level\]", key))
            })

            grouped_duties = []
            for i in duty_indices:
                year_level_id = request.POST.get(f"duties[{i}][year_level]")
                subject_ids = request.POST.getlist(f"duties[{i}][subjects][]")

                if year_level_id and subject_ids:
                    try:
                        year_level = EmisClassLevel.objects.get(pk=year_level_id, active=True)
                        subjects = EmisSubject.objects.filter(pk__in=subject_ids, active=True)

                        if subjects.exists():
                            grouped_duties.append({
                                "year_level": year_level,
                                "subjects": list(subjects),
                            })
                    except EmisClassLevel.DoesNotExist:
                        pass

            # Expand grouped duties into individual ClaimedDuty records
            for group in grouped_duties:
                year_level = group["year_level"]
                for subject in group["subjects"]:
                    # Check if this duty already exists
                    existing_duty = next(
                        (d for d in existing_duties if d.year_level_id == year_level.pk and d.subject_id == subject.pk),
                        None
                    )

                    if existing_duty:
                        # Keep existing duty
                        duties_to_keep.add(existing_duty.pk)
                    else:
                        # Create new duty
                        new_duty = ClaimedDuty.objects.create(
                            appointment=appointment,
                            year_level=year_level,
                            subject=subject,
                            created_by=request.user,
                            last_updated_by=request.user,
                        )
                        duties_to_keep.add(new_duty.pk)

            # Delete duties that are no longer selected
            duties_to_delete = existing_duty_ids - duties_to_keep
            ClaimedDuty.objects.filter(pk__in=duties_to_delete).delete()

            # Get updated duties list for response
            duties = appointment.claimed_duties.select_related("year_level", "subject").all()
            duties_html = render(request, "teacher_registration/_duty_list.html", {
                "duties": duties,
            }).content.decode("utf-8")

            return JsonResponse({
                "success": True,
                "message": "Duties saved successfully",
                "duties_html": duties_html,
                "duties_count": duties.count(),
            })

        except Exception as e:
            return JsonResponse({
                "success": False,
                "error": f"Error saving duties: {str(e)}",
            }, status=400)

    # GET: Load existing duties and group them by year_level
    existing_duties = appointment.claimed_duties.select_related("year_level", "subject").all()

    # Group duties by year_level
    grouped = defaultdict(list)
    for duty in existing_duties:
        grouped[duty.year_level].append(duty.subject)

    # Convert to list of dicts for template
    grouped_duties = [
        {"year_level": year_level, "subjects": subjects}
        for year_level, subjects in grouped.items()
    ]

    # Get available year levels and subjects for dropdowns
    year_levels = EmisClassLevel.objects.filter(active=True).order_by("label")
    subjects = EmisSubject.objects.filter(active=True).order_by("label")

    return render(
        request,
        "teacher_registration/_duty_formset.html",
        {
            "appointment": appointment,
            "grouped_duties": grouped_duties,
            "year_levels": year_levels,
            "subjects": subjects,
        },
    )
