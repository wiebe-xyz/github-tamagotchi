# Feature Specification: Admin System
**Status**: Implemented
**Created**: 2026-04-13

## Overview
The admin system provides system-level visibility and control over all pets, image generation jobs, webhook events, achievements, and sprite generation. It is separate from repo-owner access — admins are designated by GitHub login in the server config, while repo owners manage only their own pets.

## User Stories

### Admin overview page shows system health (Priority: P1)
Admins can see aggregate stats across all pets.
**Acceptance Scenarios**:
1. Given an admin visits /admin, Then the page shows total pets, active pets, dead pets, and recent activity
2. Given a non-admin visits /admin, Then they receive a 403 or redirect to login

### Admin can browse and filter all pets (Priority: P1)
The /admin/pets page lists all registered pets with filtering.
**Acceptance Scenarios**:
1. Given an admin visits /admin/pets, Then a paginated list of all pets is shown
2. Given the admin filters by stage=elder, Then only elder pets are shown
3. Given the admin filters by is_dead=true, Then only dead pets are shown

### Admin can trigger image regeneration for any pet (Priority: P1)
Per-pet image regeneration is available from the admin panel.
**Acceptance Scenarios**:
1. Given an admin is on a pet's admin detail page, When they click regenerate images, Then a new ImageGenerationJob is created for that pet
2. Given the job is created, Then it enters the queue and is processed asynchronously

### Admin can view and inspect job queue (Priority: P2)
The /admin/jobs page shows image generation job status.
**Acceptance Scenarios**:
1. Given an admin visits /admin/jobs, Then pending, processing, completed, and failed counts are shown
2. Given a job has failed 3 times (MAX_ATTEMPTS), Then it is shown as permanently failed

### Admin can view webhook events (Priority: P2)
The /admin/webhooks page shows recent webhook event history.
**Acceptance Scenarios**:
1. Given an admin visits /admin/webhooks, Then recent webhook events are listed with event_type and timestamp
2. Given a webhook failed processing, Then its failure is visible

### Admin can manage achievements and sprites (Priority: P3)
Admin pages exist for inspecting unlocked achievements and managing sprite assets.
**Acceptance Scenarios**:
1. Given an admin visits /admin/achievements, Then all pets with their unlocked achievements are visible
2. Given an admin visits /admin/sprites, Then sprite generation status per pet is shown

## Functional Requirements
- **FR-001**: All /admin/* routes require `get_admin_user` dependency (403 for non-admins)
- **FR-002**: Admin status determined by `settings.admin_github_logins` config list, synced on each request
- **FR-003**: System admin vs repo owner: system admin can manage any pet; repo owner manages only their repo's pet
- **FR-004**: /admin/pets provides paginated list with filters for stage, mood, is_dead
- **FR-005**: /admin/jobs shows ImageGenerationJob queue stats (pending/processing/completed/failed counts)
- **FR-006**: /admin/webhooks shows WebhookEvent log
- **FR-007**: /admin/achievements shows PetAchievement records
- **FR-008**: Per-pet regenerate action creates a new ImageGenerationJob with stage=None (all stages)
- **FR-009**: /api/v1/health/detailed endpoint (admin-only) returns full system status including uptime, pet stats, job run stats
- **FR-010**: Admin user is also able to use the detailed health endpoint for monitoring

## Technical Notes
- Key files: `src/github_tamagotchi/api/auth.py` (get_admin_user), `src/github_tamagotchi/api/health.py` (detailed endpoint), `src/github_tamagotchi/api/routes.py` (admin API endpoints), `src/github_tamagotchi/main.py` (admin HTML routes)
- `get_admin_user` dependency: wraps `get_current_user`, checks `user.is_admin OR user.github_login in settings.admin_github_logins`
- Admin HTML pages are Jinja2 templates served from `src/github_tamagotchi/templates/`
- ImageGenerationJob model: id, pet_id, status, stage, attempts, created_at, updated_at
- JobStatus: PENDING, PROCESSING, COMPLETED, FAILED

## Success Criteria
- SC-001: Only users in admin_github_logins can access /admin/* pages
- SC-002: Admin can trigger image regeneration without manual DB access
- SC-003: Job queue stats are accurate and update in real time on page refresh
- SC-004: Webhook event history is preserved for debugging
