# pacific-emis-teacher-registration
A standalone but integrated module of the Pacific EMIS designed to support online registration of teachers across the region.

## Access Control Architecture

This application uses a two-layer access control system that combines profile-based roles with group-based permissions.

### User Profiles

Users must have one of the following profiles:

- **SchoolStaff**: School-level users (teachers, principals, school administrators)
- **SystemUser**: System-level users (MOE officials, consultants, data analysts)

### Permission Groups

Access is controlled through Django groups. Users must be assigned to at least one group:

#### School-Level Groups (for SchoolStaff)
- **Admins**: System-wide full access to all data and functionality
- **School Admins**: Can manage staff and students at their assigned school(s)
- **Teachers**: Can create and edit students at their assigned school(s)
- **School Staff**: Read-only access to data at their assigned school(s)

#### System-Level Groups (for SystemUser)
- **System Admins**: System-wide full access (for MOE officials)
- **System Staff**: System-wide read-only access (for consultants, analysts)

### How Access Control Works

**Layer 1: App-Level Access**
- User must be authenticated
- User must have a profile (SchoolStaff OR SystemUser)
- User must belong to at least one group
- Enforced by `@require_app_access` decorator on all views

**Layer 2: Row-Level Access**
- Data filtered based on user's school assignments
- SchoolStaff see only data from their assigned schools
- SystemUser and Admins see all data
- Enforced by permission functions in `teacher_registration.permissions`

### New User Workflow

1. User signs in with Google OAuth → Django User account created
2. User sees "no permissions" page
3. Administrator goes to Django admin → Users section
4. Administrator filters by "No role assigned"
5. Administrator creates SchoolStaff or SystemUser profile
6. Administrator assigns user to appropriate group(s)
7. User can now access the system with correct permissions

### Group Permissions Matrix

| Group | Profile | Scope | Create | Edit | Delete | View |
|-------|---------|-------|--------|------|--------|------|
| **Admins** | SchoolStaff | System-wide | ✓ | ✓ | ✓ | ✓ |
| **School Admins** | SchoolStaff | Their schools | ✓ | ✓ | ✗ | ✓ |
| **Teachers** | SchoolStaff | Their schools | ✓ | ✓ | ✗ | ✓ |
| **School Staff** | SchoolStaff | Their schools | ✗ | ✗ | ✗ | ✓ |
| **System Admins** | SystemUser | System-wide | ✓ | ✓ | ✓ | ✓ |
| **System Staff** | SystemUser | System-wide | ✗ | ✗ | ✗ | ✓ |
