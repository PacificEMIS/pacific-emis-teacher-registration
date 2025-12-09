from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from core.permissions import (
    GROUP_ADMINS,
    GROUP_SCHOOL_ADMINS,
    GROUP_SCHOOL_STAFF,
    GROUP_TEACHERS,
    GROUP_SYSTEM_ADMINS,
    GROUP_SYSTEM_STAFF,
)


class Command(BaseCommand):
    help = "Create all default groups and assign permissions for the core app."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing permissions before assigning new ones",
        )

    def handle(self, *args, **options):
        reset = options.get("reset", False)

        # Define groups with their permissions
        # Format: (group_name, [permission_strings])
        # Permission strings: "app_label.codename" or just "codename" for core app
        groups_config = {
            # Admins
            "Admins": [
                "account.add_emailaddress",
                "account.add_emailconfirmation",
                "account.change_emailaddress",
                "account.change_emailconfirmation",
                "account.delete_emailaddress",
                "account.delete_emailconfirmation",
                "account.view_emailaddress",
                "account.view_emailconfirmation",
                "admin.add_logentry",
                "admin.change_logentry",
                "admin.delete_logentry",
                "admin.view_logentry",
                "auth.add_group",
                "auth.add_permission",
                "auth.add_user",
                "auth.change_group",
                "auth.change_permission",
                "auth.change_user",
                "auth.delete_group",
                "auth.delete_permission",
                "auth.delete_user",
                "auth.view_group",
                "auth.view_permission",
                "auth.view_user",
                "contenttypes.add_contenttype",
                "contenttypes.change_contenttype",
                "contenttypes.delete_contenttype",
                "contenttypes.view_contenttype",
                "core.add_schoolstaff",
                "core.add_schoolstaffassignment",
                "core.add_systemuser",
                "core.change_schoolstaff",
                "core.change_schoolstaffassignment",
                "core.change_systemuser",
                "core.delete_schoolstaff",
                "core.delete_schoolstaffassignment",
                "core.delete_systemuser",
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "core.view_systemuser",
                "integrations.add_emisclasslevel",
                "integrations.add_emisjobtitle",
                "integrations.add_emisschool",
                "integrations.add_emiswarehouseyear",
                "integrations.change_emisclasslevel",
                "integrations.change_emisjobtitle",
                "integrations.change_emisschool",
                "integrations.change_emiswarehouseyear",
                "integrations.delete_emisclasslevel",
                "integrations.delete_emisjobtitle",
                "integrations.delete_emisschool",
                "integrations.delete_emiswarehouseyear",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
                "sessions.add_session",
                "sessions.change_session",
                "sessions.delete_session",
                "sessions.view_session",
                "sites.add_site",
                "sites.change_site",
                "sites.delete_site",
                "sites.view_site",
                "socialaccount.add_socialaccount",
                "socialaccount.add_socialapp",
                "socialaccount.add_socialtoken",
                "socialaccount.change_socialaccount",
                "socialaccount.change_socialapp",
                "socialaccount.change_socialtoken",
                "socialaccount.delete_socialaccount",
                "socialaccount.delete_socialapp",
                "socialaccount.delete_socialtoken",
                "socialaccount.view_socialaccount",
                "socialaccount.view_socialapp",
                "socialaccount.view_socialtoken",
            ],
            # School Admins
            "School Admins": [
                "core.add_schoolstaff",
                "core.add_schoolstaffassignment",
                "core.change_schoolstaff",
                "core.change_schoolstaffassignment",
                "core.delete_schoolstaff",
                "core.delete_schoolstaffassignment",
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
            ],
            # School Staff
            "School Staff": [
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "core.view_systemuser",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
            ],
            # System Admins
            "System Admins": [
                "account.view_emailaddress",
                "account.view_emailconfirmation",
                "admin.view_logentry",
                "core.add_schoolstaff",
                "core.add_schoolstaffassignment",
                "core.add_systemuser",
                "core.change_schoolstaff",
                "core.change_schoolstaffassignment",
                "core.change_systemuser",
                "core.delete_schoolstaff",
                "core.delete_schoolstaffassignment",
                "core.delete_systemuser",
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "core.view_systemuser",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
            ],
            # System Staff
            "System Staff": [
                "account.view_emailaddress",
                "account.view_emailconfirmation",
                "admin.view_logentry",
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "core.view_systemuser",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
            ],
            # Teachers
            "Teachers": [
                "core.view_schoolstaff",
                "core.view_schoolstaffassignment",
                "core.view_systemuser",
                "integrations.view_emisclasslevel",
                "integrations.view_emisjobtitle",
                "integrations.view_emisschool",
                "integrations.view_emiswarehouseyear",
            ],
        }

        created_count = 0
        updated_count = 0
        permissions_assigned = 0

        for group_name, permission_codenames in groups_config.items():
            group, created = Group.objects.get_or_create(name=group_name)

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"✓ Created group: {group_name}"))
            else:
                updated_count += 1
                self.stdout.write(f"  Group already exists: {group_name}")

            # Clear existing permissions if reset flag is set
            if reset:
                group.permissions.clear()
                self.stdout.write(f"  → Cleared existing permissions for {group_name}")

            # Assign permissions
            for perm_string in permission_codenames:
                try:
                    # Parse permission string (app_label.codename)
                    if "." in perm_string:
                        app_label, codename = perm_string.split(".")
                    else:
                        app_label = "core"
                        codename = perm_string

                    # Get the permission
                    perm = Permission.objects.get(
                        content_type__app_label=app_label, codename=codename
                    )

                    # Add permission if not already assigned
                    if perm not in group.permissions.all():
                        group.permissions.add(perm)
                        permissions_assigned += 1
                        self.stdout.write(
                            f"    + Added permission: {app_label}.{codename}"
                        )

                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ! Permission not found: {app_label}.{codename} (will be created after migrations)"
                        )
                    )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Groups seeded successfully: {created_count} created, {updated_count} already existed"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Permissions assigned: {permissions_assigned} new permissions"
            )
        )
        if reset:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "  All existing permissions were cleared and reassigned"
                )
            )
