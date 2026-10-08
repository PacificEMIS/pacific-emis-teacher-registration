"""seed_groups and export_group_permissions management commands."""

from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command

from core import permissions as p

pytestmark = pytest.mark.django_db

EXPECTED_GROUPS = {
    p.GROUP_ADMINS, p.GROUP_SCHOOL_ADMINS, p.GROUP_SCHOOL_STAFF, p.GROUP_TEACHERS,
    p.GROUP_SYSTEM_ADMINS, p.GROUP_SYSTEM_STAFF,
}


def seed(*args):
    out = StringIO()
    call_command("seed_groups", *args, stdout=out)
    return out.getvalue()


class TestSeedGroups:
    def test_creates_groups_with_permissions(self):
        output = seed()
        assert EXPECTED_GROUPS <= set(Group.objects.values_list("name", flat=True))
        admins = Group.objects.get(name=p.GROUP_ADMINS)
        assert admins.permissions.filter(content_type__app_label="account", codename="add_emailaddress").exists()
        assert "Groups seeded successfully" in output

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known bug: seed_groups still lists core.add_teacher, core.change_teacher, "
            "core.delete_teacher and core.view_teacher, but there is no core.Teacher "
            "model, so every run warns 'Permission not found'. Remove the stale entries "
            "in a separate commit; this xfail then XPASSes (strict) and must be removed."
        ),
    )
    def test_every_configured_permission_exists(self):
        output = seed()
        assert "Permission not found" not in output

    def test_only_the_known_stale_permissions_are_missing(self):
        """Guards against new stale entries while the known ones await cleanup."""
        import re

        missing = set(re.findall(r"Permission not found: ([a-z_]+\.[a-z_]+)", seed()))
        assert missing <= {"core.add_teacher", "core.change_teacher", "core.delete_teacher", "core.view_teacher"}

    def test_is_idempotent(self):
        seed()
        counts = {g.name: g.permissions.count() for g in Group.objects.all()}
        output = seed()
        assert {g.name: g.permissions.count() for g in Group.objects.all()} == counts
        assert "already exists" in output
        assert "0 new permissions" in output

    def test_reset_clears_manual_additions(self):
        seed()
        teachers = Group.objects.get(name=p.GROUP_TEACHERS)
        stray = Permission.objects.filter(content_type__app_label="admin").first()
        teachers.permissions.add(stray)
        seed("--reset")
        assert not teachers.permissions.filter(pk=stray.pk).exists()

    def test_admin_and_system_admin_groups_are_not_empty(self):
        seed()
        for name in (p.GROUP_ADMINS, p.GROUP_SYSTEM_ADMINS):
            assert Group.objects.get(name=name).permissions.count() > 0, name


class TestExportGroupPermissions:
    def test_warns_when_nothing_to_export(self):
        out = StringIO()
        call_command("export_group_permissions", stdout=out)
        assert "No groups found" in out.getvalue()

    def test_dict_format_round_trips_seed_configuration(self):
        seed()
        out = StringIO()
        call_command("export_group_permissions", stdout=out)
        text = out.getvalue()
        assert "groups_config = {" in text
        assert f"'{p.GROUP_ADMINS}': [" in text
        assert "'account.add_emailaddress'," in text

    def test_list_format(self):
        seed()
        out = StringIO()
        call_command("export_group_permissions", "--format", "list", stdout=out)
        text = out.getvalue()
        assert f"{p.GROUP_TEACHERS}:" in text
        assert "groups_config" not in text
