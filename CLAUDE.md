# Claude Code Project Configuration

## Python Environment

This project uses a Conda environment named `pacific-emis-teacher-registration`.

On Windows, the Python interpreter is typically at:
- Miniconda: `C:/Users/<username>/miniconda3/envs/pacific-emis-teacher-registration/python.exe`
- Anaconda: `C:/Users/<username>/anaconda3/envs/pacific-emis-teacher-registration/python.exe`

When running Django commands, use the full path to the Conda environment's Python interpreter.

## Project Structure

- Django 5.x project
- Apps: `accounts`, `core`, `teacher_registration`, `integrations`
- Templates: `templates/` (project-level) and app-specific template directories
- Static files: `static/`

## Key Models

- `TeacherRegistration`: Main registration workflow (draft → submitted → under_review → approved/rejected)
- `SchoolStaff`: Approved teachers linked to Django User
- `SystemUser`: MOE/admin staff linked to Django User
- `RegistrationChangeLog`: Audit trail for registration status changes
