"""
Export current group permissions configuration to Python code.

This command extracts the current permission assignments from the database
and generates Python code that can be used in seed_groups.py.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = "Export current group permissions configuration to Python code."

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            default='dict',
            choices=['dict', 'list'],
            help='Output format: dict (for seed_groups.py) or list (simple list)',
        )

    def handle(self, *args, **options):
        output_format = options.get('format', 'dict')

        groups = Group.objects.prefetch_related('permissions').order_by('name')

        if not groups.exists():
            self.stdout.write(
                self.style.WARNING("No groups found in database. Run seed_groups first?")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\n# Copy this configuration to seed_groups.py\n"
                f"# Found {groups.count()} groups with permissions\n"
            )
        )

        if output_format == 'dict':
            self._output_dict_format(groups)
        else:
            self._output_list_format(groups)

    def _output_dict_format(self, groups):
        """Output in dictionary format for seed_groups.py"""
        self.stdout.write("\ngroups_config = {")

        for group in groups:
            permissions = group.permissions.select_related('content_type').order_by(
                'content_type__app_label', 'codename'
            )

            self.stdout.write(f"    # {group.name}")
            self.stdout.write(f"    '{group.name}': [")

            if permissions.exists():
                for perm in permissions:
                    perm_string = f"{perm.content_type.app_label}.{perm.codename}"
                    self.stdout.write(f"        '{perm_string}',")
            else:
                self.stdout.write("        # No permissions assigned")

            self.stdout.write("    ],")
            self.stdout.write("")

        self.stdout.write("}")

    def _output_list_format(self, groups):
        """Output in simple list format for review"""
        for group in groups:
            permissions = group.permissions.select_related('content_type').order_by(
                'content_type__app_label', 'codename'
            )

            self.stdout.write(self.style.SUCCESS(f"\n{group.name}:"))

            if permissions.exists():
                for perm in permissions:
                    perm_string = f"{perm.content_type.app_label}.{perm.codename}"
                    perm_name = perm.name
                    self.stdout.write(f"  • {perm_string:45} ({perm_name})")
            else:
                self.stdout.write("  (No permissions assigned)")
