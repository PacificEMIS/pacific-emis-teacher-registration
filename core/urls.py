"""
URL configuration for core app.

Handles URLs for core person-related models: SystemUser and SchoolStaff.
"""
from django.urls import path
from core import views

app_name = "core"

urlpatterns = [
    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),
    # System Users
    path("system-users/", views.system_user_list, name="system_user_list"),
    path("system-users/<int:pk>/", views.system_user_detail, name="system_user_detail"),
    # School Staff
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:pk>/", views.staff_detail, name="staff_detail"),
    path(
        "staff/<int:staff_id>/membership/<int:pk>/edit/",
        views.staff_membership_edit,
        name="staff_membership_edit",
    ),
    path(
        "staff/<int:staff_id>/membership/<int:pk>/delete/",
        views.staff_membership_delete,
        name="staff_membership_delete",
    ),
]
