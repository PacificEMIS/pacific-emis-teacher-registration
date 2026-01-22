"""
Views for teacher registration workflow.

This module provides views for:
- Teachers: Create, edit, submit registrations
- Admins: List, review, approve/reject registrations
"""

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery, Prefetch
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from core.decorators import require_app_access
from core.models import SchoolStaff, SchoolStaffAssignment
from integrations.models import EmisSchool
from core.emails import (
    send_new_teacher_registration_email_async,
    send_teacher_registration_submitted_email_async,
    send_teacher_registration_approved_email_async,
    send_teacher_registration_rejected_email_async,
)
from core.permissions import can_manage_pending_users
from teacher_registration.models import (
    TeacherRegistration,
    RegistrationDocument,
    RegistrationChangeLog,
)
from teacher_registration.forms import (
    TeacherRegistrationForm,
    RegistrationDocumentForm,
    RegistrationReviewForm,
    EducationRecordFormSet,
    TrainingRecordFormSet,
    ClaimedSchoolAppointmentFormSet,
)
from integrations.models import EmisTeacherPdType


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

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


def get_required_documents_status(documents):
    """
    Build a list of required documents with their upload status.

    Args:
        documents: QuerySet of RegistrationDocument objects

    Returns:
        List of dicts: [{"label": str, "uploaded": bool}, ...]
    """
    # Get all uploaded document type codes (uppercase for case-insensitive matching)
    uploaded_codes = set()
    for doc in documents:
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
def my_registration(request):
    """
    Show the teacher's current registration status or start a new one.

    - If admin: show the admin registration page
    - If user has SchoolStaff profile: redirect to dashboard
    - If user has draft registration: redirect to edit it
    - If user has submitted registration: show status
    - Otherwise: redirect to create a new registration
    """
    user = request.user

    # If admin, show the admin registration page
    if can_manage_pending_users(user):
        return redirect("teacher_registration:admin_register")

    # Check for existing registrations (prefetch change logs for history display)
    registrations = (
        TeacherRegistration.objects.filter(user=user)
        .prefetch_related("change_logs__changed_by")
        .order_by("-created_at")
    )

    # Check if user already has a SchoolStaff profile (approved teacher)
    if hasattr(user, "school_staff"):
        # Show their registration history with approved status
        return render(
            request,
            "teacher_registration/my_registration.html",
            {
                "active": "my_registration",
                "registrations": registrations,
                "is_approved": True,
            },
        )

    # If has draft, go to edit
    draft = registrations.filter(status=TeacherRegistration.DRAFT).first()
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
        user=user, status=TeacherRegistration.DRAFT
    ).first()

    if existing_draft:
        return redirect("teacher_registration:edit", pk=existing_draft.pk)

    # Check for pending registration
    pending = TeacherRegistration.objects.filter(
        user=user, status__in=[TeacherRegistration.SUBMITTED, TeacherRegistration.UNDER_REVIEW]
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
        status=TeacherRegistration.DRAFT,
        created_by=user,
        last_updated_by=user,
    )

    # Log registration creation
    RegistrationChangeLog.log_change(
        registration=registration,
        field_name="status",
        old_value="",
        new_value=TeacherRegistration.DRAFT,
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
def registration_edit(request, pk):
    """
    Edit a draft registration.

    - Owner can edit their own registration
    - Admins can edit any registration
    Save Draft: saves without validation
    Save & Submit: validates required fields before submitting
    """
    registration = get_object_or_404(TeacherRegistration, pk=pk)

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
                    required_docs_status = get_required_documents_status(documents)
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
                            "document_form": RegistrationDocumentForm(),
                            "is_admin": is_admin,
                            "required_docs_status": required_docs_status,
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

    # Get PD types for training title autocomplete
    pd_types = EmisTeacherPdType.objects.filter(active=True).order_by("label")

    # Build required documents status for checklist
    required_docs_status = get_required_documents_status(documents)

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
            "document_form": RegistrationDocumentForm(),
            "is_admin": is_admin,
            "pd_types": pd_types,
            "required_docs_status": required_docs_status,
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
    if registration.status != TeacherRegistration.DRAFT:
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
        redirect_url = "teacher_registration:admin_edit" if is_admin else "teacher_registration:edit"
        return redirect(redirect_url, pk=registration.pk)

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

    # Redirect back to appropriate edit page
    redirect_url = "teacher_registration:admin_edit" if is_admin and not is_owner else "teacher_registration:edit"
    return redirect(redirect_url, pk=registration.pk)


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
        redirect_url = "teacher_registration:admin_edit" if is_admin and not is_owner else "teacher_registration:edit"
        return redirect(redirect_url, pk=registration.pk)

    if request.method == "POST":
        document.delete()
        messages.success(request, "Document deleted.")

    # Redirect back to appropriate edit page
    redirect_url = "teacher_registration:admin_edit" if is_admin and not is_owner else "teacher_registration:edit"
    return redirect(redirect_url, pk=registration.pk)


# =============================================================================
# Admin-facing views (review workflow)
# =============================================================================


@login_required
@require_app_access
def admin_register(request):
    """
    Admin view to create a new teacher registration on behalf of a teacher.

    Creates a new Django user (if needed) and a registration for them.
    This is for teachers who don't have email/computer access.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    from django.contrib.auth import get_user_model
    from teacher_registration.forms import AdminTeacherRegistrationForm
    User = get_user_model()

    if request.method == "POST":
        form = AdminTeacherRegistrationForm(request.POST)
        if form.is_valid():
            # Create a placeholder user for this teacher
            email = form.cleaned_data.get("email", "").strip()
            first_name = form.cleaned_data.get("first_name", "").strip()
            last_name = form.cleaned_data.get("last_name", "").strip()

            # Generate a unique username/email if not provided
            if not email:
                import uuid
                email = f"teacher_{uuid.uuid4().hex[:8]}@placeholder.local"

            # Check if user with this email already exists
            existing_user = User.objects.filter(email=email).first()
            if existing_user:
                messages.error(request, f"A user with email {email} already exists.")
                return render(
                    request,
                    "teacher_registration/admin_register.html",
                    {"active": "my_registration", "form": form},
                )

            # Create the user
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=None,  # No password - can't login
            )

            # Create the registration
            registration = TeacherRegistration.objects.create(
                user=user,
                registration_type=TeacherRegistration.INITIAL,
                status=TeacherRegistration.DRAFT,
                # Copy form data to registration
                date_of_birth=form.cleaned_data.get("date_of_birth"),
                gender=form.cleaned_data.get("gender", ""),
                nationality=form.cleaned_data.get("nationality", ""),
                national_id_number=form.cleaned_data.get("national_id_number", ""),
                phone_number=form.cleaned_data.get("phone_number", ""),
                address_line_1=form.cleaned_data.get("address_line_1", ""),
                address_line_2=form.cleaned_data.get("address_line_2", ""),
                city=form.cleaned_data.get("city", ""),
                province=form.cleaned_data.get("province", ""),
                teacher_payroll_number=form.cleaned_data.get("teacher_payroll_number", ""),
                highest_qualification=form.cleaned_data.get("highest_qualification", ""),
                years_of_experience=form.cleaned_data.get("years_of_experience"),
                preferred_school=form.cleaned_data.get("preferred_school"),
                preferred_job_title=form.cleaned_data.get("preferred_job_title"),
                created_by=request.user,
                last_updated_by=request.user,
            )

            # Log registration creation
            RegistrationChangeLog.log_change(
                registration=registration,
                field_name="status",
                old_value="",
                new_value=TeacherRegistration.DRAFT,
                changed_by=request.user,
                notes=f"Registration created by admin for {first_name} {last_name}",
            )

            messages.success(request, f"Registration created for {first_name} {last_name}.")
            return redirect("teacher_registration:admin_edit", pk=registration.pk)
    else:
        form = AdminTeacherRegistrationForm()

    return render(
        request,
        "teacher_registration/admin_register.html",
        {
            "active": "my_registration",
            "form": form,
        },
    )


@login_required
@require_app_access
def admin_edit(request, pk):
    """
    Admin edits a registration on behalf of a user.

    Similar to registration_edit but for admins.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    registration = get_object_or_404(TeacherRegistration, pk=pk)

    # Check status
    if not registration.is_editable:
        messages.error(request, "This registration can no longer be edited.")
        return redirect("teacher_registration:pending_list")

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
                    documents = registration.documents.all()
                    required_docs_status = get_required_documents_status(documents)
                    return render(
                        request,
                        "teacher_registration/admin_edit.html",
                        {
                            "active": "my_registration",
                            "form": form,
                            "education_formset": education_formset,
                            "training_formset": training_formset,
                            "appointment_formset": appointment_formset,
                            "registration": registration,
                            "documents": documents,
                            "document_form": RegistrationDocumentForm(),
                            "required_docs_status": required_docs_status,
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

            # Save the user's name
            first_name = form.cleaned_data.get("first_name", "")
            last_name = form.cleaned_data.get("last_name", "")
            registration.user.first_name = first_name
            registration.user.last_name = last_name
            registration.user.save(update_fields=["first_name", "last_name"])
            messages.success(request, "Registration saved.")

            # Submit if requested
            if is_submitting:
                registration.submit(user=request.user)
                messages.success(request, "Registration submitted for review.")
                return redirect("teacher_registration:pending_list")

            return redirect("teacher_registration:admin_edit", pk=registration.pk)
        else:
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
        form = TeacherRegistrationForm(instance=registration)
        education_formset = EducationRecordFormSet(instance=registration, prefix="education_records")
        training_formset = TrainingRecordFormSet(instance=registration, prefix="training_records")
        appointment_formset = ClaimedSchoolAppointmentFormSet(instance=registration, prefix="claimed_appointments")

    documents = registration.documents.all()

    # Get PD types for training title autocomplete
    pd_types = EmisTeacherPdType.objects.filter(active=True).order_by("label")

    # Build required documents status for checklist
    required_docs_status = get_required_documents_status(documents)

    return render(
        request,
        "teacher_registration/admin_edit.html",
        {
            "active": "my_registration",
            "form": form,
            "education_formset": education_formset,
            "training_formset": training_formset,
            "appointment_formset": appointment_formset,
            "registration": registration,
            "documents": documents,
            "document_form": RegistrationDocumentForm(),
            "pd_types": pd_types,
            "required_docs_status": required_docs_status,
        },
    )


@login_required
@require_app_access
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

    # Base queryset - include drafts, submitted, under review, and rejected
    registrations_qs = TeacherRegistration.objects.filter(
        status__in=[
            TeacherRegistration.DRAFT,
            TeacherRegistration.SUBMITTED,
            TeacherRegistration.UNDER_REVIEW,
            TeacherRegistration.REJECTED,
        ]
    ).select_related("user", "preferred_school", "reviewed_by")

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
            When(status=TeacherRegistration.UNDER_REVIEW, then=Value(0)),
            When(status=TeacherRegistration.SUBMITTED, then=Value(1)),
            When(status=TeacherRegistration.REJECTED, then=Value(2)),
            When(status=TeacherRegistration.DRAFT, then=Value(3)),
            default=Value(4),
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
def registration_review(request, pk):
    """
    Review a teacher registration (approve or reject).
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    registration = get_object_or_404(
        TeacherRegistration.objects.select_related(
            "user", "preferred_school", "preferred_job_title", "reviewed_by"
        ).prefetch_related("documents"),
        pk=pk,
    )

    # Check if registration can be reviewed
    if registration.status not in [
        TeacherRegistration.SUBMITTED,
        TeacherRegistration.UNDER_REVIEW,
        TeacherRegistration.REJECTED,
    ]:
        messages.error(request, "This registration cannot be reviewed.")
        return redirect("teacher_registration:pending_list")

    # Mark as under review if not already (allows re-review of rejected registrations)
    if registration.status in [TeacherRegistration.SUBMITTED, TeacherRegistration.REJECTED]:
        registration.start_review(request.user)

    if request.method == "POST":
        form = RegistrationReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data["action"]
            comments = form.cleaned_data["comments"]

            if action == RegistrationReviewForm.ACTION_APPROVE:
                staff = registration.approve(reviewer=request.user, comments=comments)

                # Send approval email to the teacher
                from django.urls import reverse

                my_registration_url = request.build_absolute_uri(
                    reverse("teacher_registration:my_registration")
                )
                send_teacher_registration_approved_email_async(
                    registration=registration,
                    dashboard_url=my_registration_url,
                )

                messages.success(
                    request,
                    f"Registration approved. {registration.user.get_full_name()} is now a registered teacher.",
                )
                return redirect("teacher_registration:teacher_detail", pk=staff.pk)

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

    return render(
        request,
        "teacher_registration/registration_review.html",
        {
            "active": "pending_registrations",
            "registration": registration,
            "form": form,
        },
    )


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
        "user", "preferred_school", "reviewed_by", "approved_staff_profile"
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
            "status_choices": TeacherRegistration.STATUS_CHOICES,
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
    registration_status_filter = (request.GET.get("registration_status") or "").strip()

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

    # Filter by registration status
    if registration_status_filter:
        teachers_qs = teachers_qs.filter(registration_status=registration_status_filter)

    # Sorting map
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "school": (
            "latest_school_name",
            "user__last_name",
            "user__first_name",
        ),
        "status": (
            "registration_status",
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
            "registration_status": registration_status_filter,
            "schools": schools,
            "registration_status_choices": SchoolStaff.REGISTRATION_STATUS_CHOICES,
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
            "documents",
            "registration_history__change_logs",
        ),
        pk=pk,
    )

    # Get active assignments
    active_assignments = teacher.active_assignments.select_related("school", "job_title")

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
