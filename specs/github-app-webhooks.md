# Feature Specification: GitHub App Webhooks
**Status**: Partially Implemented
**Created**: 2026-09-10
**Updated**: 2026-09-16 — webhook source verification (issues #278/#279)

## Overview
Pets update from two sources today: a 30-minute background poll (`main.py::poll_repositories`, one shared bot PAT via `GitHubService`) and a live webhook endpoint (`POST /api/v1/webhooks/github`, `services/webhook.py::EVENT_HANDLERS`) that a repo owner can wire up manually. Issue #185 originally proposed replacing the manual webhook flow with a full installable GitHub App (its own auth, per-repo installation tokens, auto-registered webhooks).

Investigating a real report of this — a user who connected GitHub but still saw a stale pet — found a narrower, concrete bug ahead of that larger proposal: the poll's `GitHubService.get_repo_health()` already distinguishes "GitHub genuinely returned nothing" from "this sub-fetch failed" via `RepoHealth.failed_checks` (see `services/github.py:184`), but `main.py::_update_single_pet_inner` discarded that signal — feeding an all-default `RepoHealth` into the health/mood calculation exactly as if the repo were genuinely inactive. A private repo the shared bot PAT can't read therefore looked identical to real neglect: the pet quietly starved with no indication of *why*. This is what shipped in this PR. The full GitHub App remains the long-term direction (§ Technical Notes) but is out of scope here.

## User Stories

### A pet doesn't silently starve when the poll can't read its repo (Priority: P1)
**Acceptance Scenarios**:
1. Given a pet whose repo the shared bot account cannot read (private repo, no access), When the scheduled poll runs, Then the pet's health/mood/experience/streak are left unchanged for that cycle instead of decaying toward "neglected"
2. Given the same pet, When the poll runs, Then `Pet.last_poll_error` is set to a human-readable reason and `last_checked_at` still advances
3. Given a pet recovers access (e.g. the repo is made public, or the bot is added as a collaborator), When the next poll succeeds, Then `Pet.last_poll_error` is cleared

### The connectivity problem, and the fix, are visible — not just at registration (Priority: P1)
**Acceptance Scenarios**:
1. Given a pet with `last_poll_error` set, When its profile page is viewed, Then a banner explains why and links to webhook setup instructions
2. Given any pet's profile page, When viewed, Then the webhook setup instructions are always present (not hidden in a collapsed section, not shown only once at registration)
3. Given the pet API (`GET /api/v1/pets/{owner}/{repo}`), When called, Then the response includes `last_poll_error`
4. Given the admin overview page, When viewed, Then a "Needs attention" count and list show every pet with a non-null `last_poll_error`

### The webhook escape hatch actually works without a shared secret (Priority: P1)
The instructions this PR made permanently visible said "no secret is required" — but production unconditionally enforced `GITHUB_WEBHOOK_SECRET`-signed deliveries (`api/routes/v1/webhooks.py`), so an unsigned ping (which is all a repo owner following the instructions could send) got a 401. There's one secret for the whole app, shared across every repo's pet — handing it out so an individual owner could sign their own deliveries would let that owner forge deliveries for anyone else's repo too (issue #278). A per-pet secret was considered and rejected as more setup friction for a toy project (issue #279 / user direction).

**Acceptance Scenarios**:
1. Given a repo owner follows the on-page webhook instructions exactly (no secret configured on GitHub's side), When GitHub delivers the event, Then it is accepted
2. Given a request to the webhook endpoint whose source IP is not one GitHub publishes as a webhook sender, When it arrives, Then it is rejected with 403, regardless of payload content
3. Given GitHub's published IP ranges can't be fetched and none have ever been cached, When a request arrives, Then it is rejected (fails closed, not open)
4. Given the ranges were already cached successfully, When a later refresh attempt fails (transient outage), Then the stale cache is still used rather than rejecting everything

## Functional Requirements
- **FR-001**: `_update_single_pet_inner` checks `health.failed_checks` after `get_repo_health()`; if `"last_commit"` is present (the check that most directly drives health/mood/streak), the poll attempt is treated as inconclusive — no health/mood/experience/streak mutation, `last_poll_error` set, `last_checked_at` still updated, and the cycle moves on to the next pet
- **FR-002**: Any other combination of `failed_checks` (partial, non-critical, or purely `rate_limited:*` entries) keeps existing behavior unchanged
- **FR-003**: `Pet.last_poll_error: str | None` (migration `034_add_pet_last_poll_error.py`) is cleared on the next poll that doesn't hit FR-001's condition
- **FR-004**: `PetResponse` includes `last_poll_error`, mirroring what the MCP tool already exposes as `sync_warnings` (`mcp/server.py:241,667`)
- **FR-005**: The pet profile page shows a banner (with the error message and the most recent `WebhookEvent` for that repo, if any) when `last_poll_error` is set, plus an always-visible "Enable real-time updates" section (`templates/_webhook_setup.html`, shared with `register_complete.html`)
- **FR-006**: The admin overview page shows a "Needs attention" stat and a table of affected repos (`pet.last_poll_error`, `pet.last_checked_at`)
- **FR-007**: `POST /api/v1/webhooks/github` requires the request's origin IP to match one of GitHub's currently-published webhook-sending ranges (`services/webhook.is_github_webhook_source`, ranges from `GET https://api.github.com/meta`, cached 1h) — replaces the previous shared-secret HMAC signature check entirely, not in addition to it
- **FR-008**: The origin IP is read from the last entry of `X-Forwarded-For` (the hop our own reverse proxy appended), falling back to the direct TCP peer — never an earlier, client-suppliable entry (`api/routes/v1/webhooks.py::_client_ip`)

## Technical Notes
- Key files: `src/github_tamagotchi/main.py` (`_update_single_pet_inner`, `pet_profile`, `admin_overview`), `src/github_tamagotchi/models/pet.py`, `src/github_tamagotchi/schemas/pets.py`, `src/github_tamagotchi/templates/_webhook_setup.html`, `alembic/versions/034_add_pet_last_poll_error.py`, `src/github_tamagotchi/services/webhook.py` (`is_github_webhook_source`), `src/github_tamagotchi/api/routes/v1/webhooks.py` (`_client_ip`)
- `RepoHealth.failed_checks` (`services/github.py:28-53`) was already the right signal — this PR is the consumer, not a new producer
- The existing manual webhook flow (`services/webhook.py`, `api/routes/v1/webhooks.py`) needs no bot-account read access at all, since GitHub pushes the event payload directly — it is the already-working fix for the private-repo case, just previously buried in a collapsed `<details>` shown once at registration
- No new models, no new auth. The per-user OAuth token (`User.encrypted_token`) is unrelated to this fix — it's checked once at registration time and is not used by the ongoing poll, which always uses the single shared `settings.github_token`
- **Why source IP instead of a secret** (added 2026-09-16, issues #278/#279): unlike an HTTP header, the TCP source address can't be forged by an arbitrary internet client — completing the handshake requires actually holding that address. GitHub publishes the ranges it sends webhooks from (`/meta`'s `hooks` key) specifically so a receiver can rely on this instead of a per-sender secret. `Settings.github_webhook_secret` and `services.webhook.verify_signature` are left in place but unused by the route — no longer part of the trust model, not deleted, since neither is otherwise harmful
- IP ranges are cached in-process (module-level, 1h TTL) rather than in the database or the shared Postgres-backed KV store built for OAuth client persistence (#262) — GitHub's ranges change rarely and a per-pod cache that occasionally refetches after a restart is a fine trade for not adding a DB round-trip to every webhook delivery

### Deferred: the full GitHub App (tracked as a follow-up issue linked from #185)
The original proposal — an installable GitHub App replacing the shared-PAT poll with per-installation tokens, auto-registered webhooks, immediate poll on install, `create`/`delete` event handling, `X-GitHub-Delivery` dedup, retry/backoff, and PR-merge-triggered mood recalculation — remains the right long-term direction, particularly for repos where even the manual webhook route is inconvenient to set up. It was not built here: this PR's job was to stop the silent-starvation bug and make the existing, already-working webhook escape hatch visible, without introducing a new auth subsystem for a problem that didn't require one.

## Success Criteria
- SC-001: A pet whose repo the bot can't read no longer trends toward "neglected" purely from failed fetches
- SC-002: Every pet with a connectivity problem is discoverable from its own profile page, the pet API, and the admin overview — none of these existed before this PR
- SC-003: The webhook setup instructions are visible on every pet's page on an ongoing basis, not only once immediately after registration
- SC-004: A repo owner can follow the on-page instructions verbatim and get a working webhook with zero secret-management steps, while a request that isn't actually from GitHub is still rejected
