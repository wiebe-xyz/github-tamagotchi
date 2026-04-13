# Feature Specification: API Shared Abstractions

**Feature Branch**: `001-api-layered-architecture`
**Created**: 2026-04-13
**Status**: Implemented

## Overview

After splitting the API monolith into 9 domain-scoped router files (spec 001), the individual
handlers still carried significant inline duplication: the same pet-not-found guard appeared 20
times, the same ownership check 4 times, the same image-generation loop twice, and domain logic
like contributor standing classification lived directly in HTTP handlers.

This spec captures the second pass: introducing shared abstractions that eliminate the duplication
and push domain logic to the right layer.

---

## User Stories

### Story 1 — Developer can add a guarded handler without copy-pasting boilerplate (Priority: P1)

A developer adding a new endpoint that requires an existing pet and ownership verification should be
able to do so in two lines, not eight.

**Acceptance Scenarios**:

1. **Given** a new handler needs a pet-or-404, **When** the developer writes it, **Then** they call
   `await get_pet_or_404(repo_owner, repo_name, session)` — one line
2. **Given** a new handler needs ownership enforcement, **When** the developer writes it, **Then**
   they call `require_pet_owner(pet, user)` — one line
3. **Given** both are needed, **Then** the handler body contains no ad-hoc `if not pet` or
   `if pet.user_id != user.id` blocks

---

### Story 2 — Business logic lives at the right layer (Priority: P1)

Pet state mutations (resurrection, reset), image generation orchestration, and contributor standing
classification should not live in HTTP handler functions.

**Acceptance Scenarios**:

1. **Given** the resurrect handler, **When** a developer reads it, **Then** it contains only
   timing/validation checks and a single `pet_crud.resurrect_pet(session, pet)` call — no direct
   field assignments
2. **Given** the reset handler, **When** a developer reads it, **Then** it delegates to
   `pet_crud.reset_pet(session, pet)` — no inline mutation of 11 fields
3. **Given** the contributor badge handler, **When** a developer reads it, **Then** standing
   classification is a single call to `classify_contributor_standing(...)` defined in
   `services/badge.py`

---

### Story 3 — Generate and regenerate share one implementation (Priority: P2)

The generate-images and regenerate-images endpoints were byte-for-byte identical except for a
leading `storage.delete_images` call. A bug fix or change to one must not require updating both.

**Acceptance Scenarios**:

1. **Given** a change to how images are generated per stage, **When** the developer makes it,
   **Then** they edit `_generate_all_stages` once and both endpoints pick it up
2. **Given** the two endpoint handlers, **When** a developer reads them, **Then** each is under
   10 lines and the difference between them is obvious

---

## Functional Requirements

- **FR-001**: `get_pet_or_404(repo_owner, repo_name, session)` must be the canonical pet lookup
  used by all handlers — no handler may inline the 4-line fetch+check pattern
- **FR-002**: `require_pet_owner(pet, user)` must be the canonical ownership guard — no handler
  may inline `if pet.user_id != user.id and not user.is_admin`
- **FR-003**: Pet state mutations (resurrection fields, reset fields) must live in `crud/pet.py`,
  not in route handlers
- **FR-004**: `update_images_generated_at` and `update_canonical_appearance` must live in
  `crud/pet.py` — route modules must not execute raw `UPDATE` statements
- **FR-005**: Contributor standing classification must live in `services/badge.py` alongside
  `ContributorStanding`
- **FR-006**: Duplicate generate/regenerate logic must be extracted into a shared private helper
- **FR-007**: SVG response headers must be defined as a named constant — no inline dict literals
  per response
- **FR-008**: Pagination response construction must be a shared helper, not duplicated per endpoint
- **FR-009**: All existing tests must pass without modification

## Abstractions Introduced

### `api/dependencies.py`

| Symbol | Type | Purpose |
|--------|------|---------|
| `get_pet_or_404(repo_owner, repo_name, session)` | `async def` | Fetch pet or raise 404 — was written but unused |
| `require_pet_owner(pet, user)` | `def` | Raise 403 if user doesn't own pet |

### `crud/pet.py`

| Symbol | Type | Purpose |
|--------|------|---------|
| `resurrect_pet(db, pet)` | `async def` | Reset dead pet to egg state, increment generation |
| `reset_pet(db, pet)` | `async def` | Full stat reset, increment generation |
| `update_images_generated_at(db, owner, repo)` | `async def` | Stamp images_generated_at timestamp |
| `update_canonical_appearance(db, owner, repo, appearance)` | `async def` | Persist canonical appearance string |

### `services/badge.py`

| Symbol | Type | Purpose |
|--------|------|---------|
| `classify_contributor_standing(commits_30d, is_top_contributor, has_failed_ci, days_since_last_commit)` | `def` | Map activity stats to `ContributorStanding` |

### `api/routes/v1/pets/media.py` (private)

| Symbol | Type | Purpose |
|--------|------|---------|
| `_generate_all_stages(repo_owner, repo_name, storage, session)` | `async def` | Generate all stage images, upload, stamp timestamp |
| `_require_image_generation()` | `def` | Raise 503 if generation or storage is not configured |
| `_SVG_HEADERS` | `dict` | Cache-Control + Content-Type headers for SVG responses |

### `api/routes/v1/social.py` (private)

| Symbol | Type | Purpose |
|--------|------|---------|
| `_SVG_HEADERS` | `dict` | Cache-Control + Content-Type headers for SVG responses |

### `api/routes/v1/pets/crud.py` (private)

| Symbol | Type | Purpose |
|--------|------|---------|
| `_build_pet_list_response(pets, total, page, per_page)` | `def` | Construct `PetListResponse`, shared by list_pets and list_my_pets |

## Duplication Eliminated

| Pattern | Before | After |
|---------|--------|-------|
| Inline pet-or-404 fetch+check | 20 call sites across 7 files | `get_pet_or_404` wired everywhere |
| Inline ownership 403 check | 4 call sites | `require_pet_owner` |
| Pet resurrection field mutations | 9 direct assignments in handler | `pet_crud.resurrect_pet` |
| Pet reset field mutations | 11 direct assignments in handler | `pet_crud.reset_pet` |
| Raw `UPDATE images_generated_at` in route | 3 call sites | `pet_crud.update_images_generated_at` |
| Raw `UPDATE canonical_appearance` in route | 1 call site | `pet_crud.update_canonical_appearance` |
| generate/regenerate image loop | 2 copies (identical except delete step) | `_generate_all_stages` |
| Image generation 503 preflight pair | 4 pairs | `_require_image_generation` |
| SVG response headers dict literal | 4 inline dicts | `_SVG_HEADERS` constant |
| Pagination response construction | 2 copies | `_build_pet_list_response` |
| Contributor standing if/elif chain | Inline in handler | `classify_contributor_standing` |

## Success Criteria

- **SC-001**: No handler contains an inline `if not pet: raise HTTPException(404)` block
- **SC-002**: No handler contains an inline `if pet.user_id != user.id` check
- **SC-003**: `resurrect_pet` and `reset_pet` exist in `crud/pet.py` with no field mutation in
  the corresponding route handlers
- **SC-004**: `classify_contributor_standing` exists in `services/badge.py` and is the only place
  standing is computed
- **SC-005**: `generate_pet_images` and `regenerate_pet_images` handlers are each under 12 lines
- **SC-006**: All 1121 existing tests pass without modification
- **SC-007**: mypy and ruff pass with no new suppressions

## Assumptions

- The `_require_repo_admin` duplicate in `admin.py` is intentionally kept because merging it with
  `dependencies.py`'s `require_repo_admin` would require `dependencies.py` to import
  `github_tamagotchi.api.routes`, creating a circular import. Tests patch the patchable symbols at
  `github_tamagotchi.api.routes.*`. This is tracked as a known limitation — resolving it would
  require test changes or a dependency-override approach.
- The `enqueue_image_if_available` pattern (3 call sites) is intentionally left as-is: extracting
  it would break the `_api_routes.get_image_provider` test-patch path unless the helper were placed
  in `routes/__init__.py`, which would add business logic to the aggregator module.
