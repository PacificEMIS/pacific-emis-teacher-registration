"""
URL configuration for teacher_registration app.

This app holds the app-level permission anchor and redirects to core functionality.
The dashboard and all core functionality (Teachers, SchoolStaff, SystemUser) is in the core app.
"""
from django.urls import path
from django.views.generic import RedirectView

app_name = "teacher_registration"

urlpatterns = [
    # Redirect to core dashboard
    path("", RedirectView.as_view(pattern_name="core:dashboard", permanent=False), name="dashboard"),
]
