"""
URL configuration for teacher_registration app.

Routes for:
- Teacher self-registration workflow
- Admin review of pending registrations
"""

from django.urls import path
from teacher_registration import views

app_name = "teacher_registration"

urlpatterns = [
    # Public (unauthenticated) - teacher self-registration landing
    path("", views.public_landing, name="public_landing"),
    path("start/", views.public_start, name="public_start"),
    path("signout/", views.public_signout, name="public_signout"),
    # Teacher-facing (self-registration)
    path("my-registration/", views.my_registration, name="my_registration"),
    path("register/", views.registration_create, name="create"),
    path("<int:pk>/edit/", views.registration_edit, name="edit"),
    path("<int:pk>/submit/", views.registration_submit, name="submit"),
    path("<int:registration_pk>/documents/upload/", views.document_upload, name="document_upload"),
    path(
        "<int:registration_pk>/documents/<int:pk>/delete/",
        views.document_delete,
        name="document_delete",
    ),
    # Admin-facing (create registration for users)
    path("admin/register/", views.admin_register, name="admin_register"),
    path("admin/<int:pk>/edit/", views.admin_edit, name="admin_edit"),
    # Admin-facing (review workflow)
    path("pending/", views.pending_registrations_list, name="pending_list"),
    path("<int:pk>/review/", views.registration_review, name="review"),
    path("<int:pk>/delete/", views.registration_delete, name="registration_delete"),
    path("history/", views.registration_history, name="history"),
    # Teachers (approved teaching staff)
    path("teachers/", views.teachers_list, name="teachers_list"),
    path("teachers/<int:pk>/", views.teacher_detail, name="teacher_detail"),
    path("teachers/<int:pk>/delete/", views.teacher_delete, name="teacher_delete"),
]
