# Claude Code Project Configuration

## Python Environment

This project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management. Python version is pinned in `.python-version` (3.12); dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

First-time setup:
```
uv sync
uv run pre-commit install
```

Run Django commands through uv (it auto-uses the project `.venv`):
```
uv run python manage.py check
uv run python manage.py runserver
```

## Deployment: `requirements.txt`

The Ansible deployment playbook installs production dependencies via `pip install -r requirements.txt`, so a committed `requirements.txt` must stay in sync with `uv.lock`.

This is automated by a pre-commit hook (`.pre-commit-config.yaml`) that regenerates `requirements.txt` whenever `pyproject.toml` or `uv.lock` is staged. If the hook modifies the file, the commit aborts — `git add requirements.txt` and recommit.

To regenerate manually:
```
uv export --format requirements-txt --no-hashes --no-emit-project --no-dev -o requirements.txt
```

Do not hand-edit `requirements.txt`; edit `pyproject.toml` and run `uv lock` (or `uv add` / `uv remove`) instead.

## Database Migrations

See global `~/.claude/CLAUDE.md` — migrations are never run automatically.

## Project Structure

- Django 5.x project
- Apps: `accounts`, `core`, `teacher_registration`, `integrations`
- Templates: `templates/` (project-level) and app-specific template directories
- Static files: `static/`

## Key Models

- `TeacherRegistration`: Main registration workflow (draft → submitted → under_review → ready_for_approval → approved/rejected)
- `SchoolStaff`: Approved teachers linked to Django User
- `SystemUser`: MOE/admin staff linked to Django User
- `RegistrationChangeLog`: Audit trail for registration status changes

## Badge Color Schemes

Two distinct CSS palettes in `static/teacher_registration/teacher_registration.css` keep application workflow and acquired registration status visually separate:

**Application Flow** (`bg-app-*`) — Traffic Light palette:
- `bg-app-draft` → #78909c (slate)
- `bg-app-submitted` → #1565c0 (blue)
- `bg-app-under-review` → #f9a825 (amber, dark text)
- `bg-app-ready-for-approval` → #9e9d24 (olive)
- `bg-app-approved` → #43a047 (emerald)
- `bg-app-rejected` → #e53935 (crimson)
- `bg-app-expired` → #e53935 (crimson)

**Registration Status** (`bg-reg-*`) — Royal Purple hierarchy:
- `bg-reg-full` → #4a148c (deep purple)
- `bg-reg-conditional` → #7b1fa2 (purple)
- `bg-reg-provisional` → #ab47bc (orchid)
- `bg-reg-limited` → #ce93d8 (lavender, dark text)
- `bg-reg-expired` → #757575 (gray)

The `badge_class` property on `EmisTeacherRegistrationStatus` maps status labels to `bg-reg-*` classes automatically.

## CSS and Styles

**IMPORTANT**: Never put CSS in Django templates — no inline `style=""` attributes and no `<style>` blocks. All styles must go in the appropriate static CSS file:
- `static/app/admin.css` — layout, sidebar, login page, general UI
- `static/teacher_registration/teacher_registration.css` — registration-specific styles, badge palettes
- `static/app/reports.css` — PDF report styles

Always create CSS classes in these files and reference them in templates.

## Date Formatting

House style ("profile B"): ISO `YYYY-MM-DD` for dates in tables, detail lists, and
form inputs; spelled-month `18 Jun 2026` for prose, emails, PDFs, and certificates.
Datetimes are stored UTC and shown ISO with an explicit timezone label.

The prose style is centralized in `core/dateformat.py` (`PROSE_DATE_FORMAT`) — change
it there to update every prose date at once. Use it via the `app_date` template filter
(`{% load dates %}` then `{{ value|app_date }}`) or the `app_date()` Python function in
views/emails. ISO dates stay as plain `{{ value|date:"Y-m-d" }}` and are not centralized.

## Django Template Comments

**IMPORTANT**: `{# ... #}` is for **single-line** comments only. For multi-line blocks use `{% comment %}...{% endcomment %}`:
```django
{% comment "Reason for commenting out" %}
  <p>Multi-line content here</p>
{% endcomment %}
```
