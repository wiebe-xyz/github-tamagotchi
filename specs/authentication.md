# Feature Specification: Authentication
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Authentication is via GitHub OAuth. After the OAuth dance, the server issues a JWT stored in an HttpOnly cookie. Admin status is determined at runtime by matching the user's GitHub login against a config list, ensuring admin access can be revoked without a database migration.

## User Stories

### User logs in via GitHub (Priority: P1)
A user visits /auth/github and is redirected through GitHub's OAuth flow.
**Acceptance Scenarios**:
1. Given a user visits /auth/github, Then they are redirected to GitHub's authorize URL with a CSRF state token
2. Given GitHub calls back to /auth/callback with a valid code and state, Then a JWT session cookie is set and the user is redirected to /register
3. Given the state is missing or expired (10-minute TTL), Then the callback returns 400

### GitHub token is encrypted before storage (Priority: P1)
OAuth access tokens are not stored in plaintext.
**Acceptance Scenarios**:
1. Given token_encryption_key is set in config, When a user authenticates, Then the GitHub token is Fernet-encrypted before being written to the database
2. Given token_encryption_key is not set, Then the token is not stored (encrypted_token remains null)

### Admin status syncs from config on every request (Priority: P1)
Adding or removing a login from admin_github_logins takes effect without restarting.
**Acceptance Scenarios**:
1. Given user.github_login is in settings.admin_github_logins, When get_current_user is called, Then user.is_admin is set to True and flushed
2. Given user.github_login is removed from admin_github_logins, When get_current_user is called, Then user.is_admin is set to False and flushed
3. Given a request to an admin-gated route with a non-admin user, Then 403 is returned

### Session cookie expires after 24 hours (Priority: P1)
Sessions do not last indefinitely.
**Acceptance Scenarios**:
1. Given jwt_expire_minutes = 1440 (default), When a session cookie is set, Then max_age = 86400 seconds
2. Given a cookie with an expired JWT, When get_current_user is called, Then 401 is returned
3. Given a request with no cookie, Then get_current_user raises 401

### Optional authentication allows public browsing (Priority: P2)
Most pages are accessible without login; auth is only required for ownership actions.
**Acceptance Scenarios**:
1. Given no session cookie, When a pet profile page is loaded, Then the page renders (get_optional_user returns None)
2. Given no session cookie, When a pet creation endpoint is called, Then 401 is returned

## Functional Requirements
- **FR-001**: OAuth scopes requested: `repo,read:user,read:org`
- **FR-002**: CSRF state tokens stored in-memory with 10-minute TTL; cleaned up on each /auth/github request
- **FR-003**: JWT payload: `sub` (user ID), `exp` (expiry), `iat` (issued at)
- **FR-004**: JWT algorithm: HS256; secret from `jwt_secret_key` config
- **FR-005**: Cookie: `session_token`, HttpOnly=True, Secure=(not debug), SameSite=lax
- **FR-006**: `is_admin` synced from `settings.admin_github_logins` on every authenticated request
- **FR-007**: `get_admin_user` dependency — wraps `get_current_user`, raises 403 if not admin
- **FR-008**: `get_optional_user` dependency — returns None (not 401) if unauthenticated
- **FR-009**: Logout endpoint (POST /auth/logout) deletes the session cookie
- **FR-010**: User records: github_id, github_login, github_avatar_url, encrypted_token, is_admin

## Technical Notes
- Key files: `src/github_tamagotchi/api/auth.py`, `src/github_tamagotchi/core/config.py`, `src/github_tamagotchi/services/token_encryption.py`
- In-memory `_oauth_states` dict keyed by state token, value is creation datetime
- `_create_jwt(user_id)` and `_decode_jwt(token)` are internal helpers
- `create_or_update_user()` upserts by github_id
- Token encryption uses Fernet symmetric encryption; key is base64-encoded 32 bytes
- `admin_github_logins` config default: `["webwiebe"]`

## Success Criteria
- SC-001: A user can log in, register a pet, and log out within a single browser session
- SC-002: An expired cookie results in a clean 401 (not a 500)
- SC-003: Admin status reflects config changes without restarting the server
- SC-004: GitHub tokens are encrypted at rest when key is configured
