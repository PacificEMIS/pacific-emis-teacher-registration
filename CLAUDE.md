# Claude Code Project Configuration

## Python Environment

This project uses a Conda environment named `pacific-emis-teacher-registration`.

When running Django commands, use the full path to the Conda environment's Python interpreter (see `CLAUDE.local.md` for the machine-specific path).

Example:
```
"<path-to-env>/python.exe" manage.py check
```

## Database Migrations

**IMPORTANT**: Do NOT run `makemigrations` or `migrate` commands automatically. The user runs all database migrations manually. When model changes require migrations, inform the user that they need to run migrations, but do not execute the commands yourself.

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

## Django Template Comments

**IMPORTANT**: `{# ... #}` is for **single-line** comments only. For multi-line blocks use `{% comment %}...{% endcomment %}`:
```django
{% comment "Reason for commenting out" %}
  <p>Multi-line content here</p>
{% endcomment %}
```
