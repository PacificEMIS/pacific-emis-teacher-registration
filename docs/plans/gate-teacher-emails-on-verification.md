# Gate teacher-facing emails on account verification + add manual invitation

## Background

Today, when staff create a teacher registration on behalf of a teacher
([views.py:362-473](../../teacher_registration/views.py#L362-L473)), a `User`
is created with the staff-entered email and an unusable password. No
notification is sent to the teacher at creation (correct), but on
**approval / rejection / forced expiry / renewal-resend**,
[core/emails.py](../../core/emails.py) sends to `user.email` directly with no
check that the address has actually been claimed by the intended teacher. The
only guard is `"@placeholder" in user.email`, which never triggers in the
staff-create path.

Risk: a typo in the staff-entered email mails a private workflow status to a
stranger.

## Goal

Stop sending teacher-bound notifications until the teacher has proven control
of the email address (by signing in via Google OAuth, which is already the only
login path). Give admins a manual "Send Invitation to Connect" button so they
can decide when to invite each teacher.

## Rollout strategy

Phased, to give staff time to understand the workflow before any teacher-visible
email goes out:

- **Phase 1 (this issue)**: silent creation, no auto-invitation. Admins
  manually send an invitation per teacher via a button on the teacher profile.
- **Phase 2 (future)**: once staff are well-versed in the basics, optionally
  auto-send the invitation at staff-create time. The same button stays in
  place, simply labeled "Re-send Invitation to Connect".

## Scope — Phase 1

### In scope

1. Detect "verified" via existing `user.socialaccount_set.exists()` — same
   convention already used at
   [views.py:516](../../teacher_registration/views.py#L516). No schema change
   required.
2. Gate the three teacher-bound helpers in
   [core/emails.py](../../core/emails.py) on that check:
   - `send_teacher_registration_approved_email`
     ([line 225](../../core/emails.py#L225))
   - `send_teacher_registration_rejected_email`
     ([line 289](../../core/emails.py#L289))
   - `send_teacher_registration_expired_email`
     ([line 359](../../core/emails.py#L359))

   Add a shared `_is_email_verified(user)` helper. When unverified, log and
   skip — same pattern as the existing `@placeholder` guard.
3. New helper `send_teacher_invitation_email(*, user, claim_url=None)` in
   [core/emails.py](../../core/emails.py), with text + HTML templates in
   `templates/emails/teacher_invitation.{txt,html}`. Content: neutral — "An
   account has been created for you in {emis_context} {app_name}. Sign in with
   Google using this email to claim it and view your registration." Do NOT
   include workflow status detail (so it is safe to send to an unverified
   address).
4. New view `teacher_resend_invitation(request, pk)` in
   [teacher_registration/views.py](../../teacher_registration/views.py),
   mirroring the shape of `teacher_resend_renewal_notification`
   ([line 1518](../../teacher_registration/views.py#L1518)): POST-only, gated
   by `can_manage_pending_users`, AJAX-aware (return JSON when
   `X-Requested-With` is `XMLHttpRequest`, else redirect with a message).
5. New URL `teacher_registration:teacher_resend_invitation` in
   [teacher_registration/urls.py](../../teacher_registration/urls.py).
6. **UI: "Send Invitation to Connect" / "Re-send Invitation to Connect"
   button** on
   [teacher_registration/templates/teacher_registration/teacher_detail.html](../../teacher_registration/templates/teacher_registration/teacher_detail.html).
   Label switches based on whether an invitation has previously been sent (see
   tracking below). Hidden when `user.socialaccount_set.exists()` (no need to
   invite a verified user).
7. **UI: "Unverified email" indicator** — small badge next to the teacher's
   email on `teacher_detail.html`, on `pending_list.html`, and on the
   registration `review` page. CSS class added to
   [static/teacher_registration/teacher_registration.css](../../static/teacher_registration/teacher_registration.css)
   per the project's no-inline-CSS rule.
8. **UI: Suppressed-email notice** — when approval / rejection / expiry happens
   against an unverified user, surface a clear note in the registration
   timeline / detail view: "Teacher email not yet verified — notification was
   NOT sent. Use 'Send Invitation to Connect' on the teacher profile to invite
   them."
9. **Invitation tracking** — small new model `UserInvitation` (one row per
   send) with `user`, `sent_at`, `sent_by`. Keeps history, supports "last sent
   2 days ago" affordance on the button, and is the data behind the "Send" vs
   "Re-send" label switch. Lives in `accounts` or `teacher_registration` — to
   be decided; `accounts` feels right.
10. Tests covering:
    - unverified user does not receive approval/rejection/expiry emails
    - verified user does receive them
    - invitation send creates a `UserInvitation` row
    - re-send works
    - button is hidden for verified users

### Out of scope (Phase 2, separate future issue)

- Automatic invitation at staff-create time
- Bulk invitation actions on `pending_list.html`
- In-app notification center for suppressed messages
- Email-link-based verification (we're relying entirely on Google OAuth for
  verification, consistent with the rest of the app)

## Acceptance criteria

- Approving, rejecting, or force-expiring a registration belonging to a teacher
  with no linked Google account sends **no email to the teacher**, and the
  action is logged.
- The same actions on a teacher with a linked Google account behave exactly as
  they do today.
- Admins see a clear "Unverified email — notification suppressed" message in
  the UI after performing a workflow action against an unverified user.
- A "Send Invitation to Connect" button appears on the teacher profile for
  unverified users, sends a neutral invitation email, and updates the button to
  "Re-send Invitation to Connect (last sent &lt;time&gt;)" after sending.
- The button is not visible for users who already have a linked Google account.
- Existing teachers (those with a linked social account, or those who
  self-registered) are unaffected.

## Technical notes / decisions to make

- **Why `socialaccount_set.exists()` and not django-allauth's
  `EmailAddress.verified`**: the project already uses this pattern at
  [views.py:516](../../teacher_registration/views.py#L516), and Google OAuth is
  the only login method, so they're equivalent. Keeping one convention is
  cheaper than introducing a second.
- **Migration**: no data migration needed. Existing teachers either (a)
  self-registered, in which case they have a `SocialAccount` row already, or
  (b) were staff-created and haven't logged in — in which case the new
  behavior correctly identifies them as unverified. Worth a one-line callout in
  the PR description so you can spot-check before merging.
- **Email field re-edit**: today, staff can edit a teacher's email while the
  user has no linked Google account
  ([views.py:516](../../teacher_registration/views.py#L516)). That stays as-is
  — useful for fixing typos before sending the invitation.

## Phase 2 preview (for context only — not this issue)

Once staff are comfortable with manual invitations, add an automatic invitation
send inside `staff_register_teacher`
([views.py:362](../../teacher_registration/views.py#L362)) and
`teacher_renew_on_behalf`
([views.py:1654](../../teacher_registration/views.py#L1654)), reusing
`send_teacher_invitation_email`. The button stays as "Re-send Invitation to
Connect" with no other UI change.

## Open questions

1. **Invitation tracking**: dedicated `UserInvitation` model (history + audit
   trail), or just two fields on a `UserProfile` (last-sent + last-sent-by,
   overwritten each time)? The model is more correct, the two-field approach
   is simpler.
2. **Suppressed-email surfacing**: just an inline notice on the teacher
   profile, or also a row in `RegistrationChangeLog` ("Approval email NOT
   sent — teacher email unverified")? Leaning toward a log row so it's
   permanent.
3. **Button placement on teacher_detail**: next to the email address inline,
   or as a top-right action button alongside any existing actions on that
   page?
