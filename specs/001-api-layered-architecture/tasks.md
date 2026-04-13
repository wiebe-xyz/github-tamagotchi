# Tasks: API Layered Architecture

**Input**: Design documents from `/specs/001-api-layered-architecture/`
**Prerequisites**: plan.md ✅, spec.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, etc.)

---

## Phase 1: Setup (Directory Structure)

**Purpose**: Create the new package structure without touching any existing files.

- [ ] T001 Create `src/github_tamagotchi/api/routes/` package directory with empty `__init__.py`
- [ ] T002 Create `src/github_tamagotchi/services/orchestration/` package directory with empty `__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helpers and service skeletons that all domain routers will depend on.

**⚠️ CRITICAL**: No router or service implementation can begin until this phase is complete.

- [ ] T003 [US5] Create `src/github_tamagotchi/api/dependencies.py` with `get_pet_or_404(repo_owner, repo_name, session)` and `require_repo_admin(pet, current_user)` helpers — extract from existing duplicate usages in `api/routes.py`
- [ ] T004 Read `src/github_tamagotchi/api/routes.py` lines 1–100 to understand imports, shared constants, and `router = APIRouter()` wiring so all sub-routers use the same patterns

**Checkpoint**: Foundation ready — all domain routers and services can now be created.

---

## Phase 3: User Stories 1 & 2 — Domain Router Split (Priority: P1) 🎯 MVP

**Goal**: Replace the monolithic `api/routes.py` with 9 focused domain routers. Each router contains only HTTP handlers (parse request → call service/crud → return response). Handlers extracted verbatim where no orchestration is needed; orchestration-heavy ones become thin stubs calling Phase 4 services.

**Independent Test**: All 35 endpoint URLs return the same responses as before. Running `pytest` after the cutover in T039 passes.

- [ ] T005 [P] [US1] Implement `src/github_tamagotchi/api/routes/pets_crud.py` — endpoints: `POST /pets`, `GET /pets`, `GET /pets/{owner}/{repo}`, `DELETE /pets/{owner}/{repo}`, `GET /me/pets`, `POST /pets/{owner}/{repo}/feed`
- [ ] T006 [P] [US1] Implement `src/github_tamagotchi/api/routes/pets_appearance.py` — endpoints: `PUT /pets/{owner}/{repo}/style`, `PUT /pets/{owner}/{repo}/name`, `PUT /pets/{owner}/{repo}/badge-style`, `GET /pets/{owner}/{repo}/skins`, `PUT /pets/{owner}/{repo}/skin`
- [ ] T007 [P] [US1] Implement `src/github_tamagotchi/api/routes/pets_info.py` — endpoints: `GET /pets/{owner}/{repo}/characteristics`, `GET /pets/{owner}/{repo}/comments`, `POST /pets/{owner}/{repo}/comments`, `GET /pets/{owner}/{repo}/achievements`, `GET /pets/{owner}/{repo}/milestones`, `GET /pets/{owner}/{repo}/contributors`, `GET /pets/{owner}/{repo}/blame-board`
- [ ] T008 [P] [US1] Implement `src/github_tamagotchi/api/routes/system.py` — endpoints: `GET /styles`, `GET /badge-styles`, `GET /health/image-provider`, `GET /admin/queue/stats`
- [ ] T009 [US1] Implement `src/github_tamagotchi/api/routes/pets_actions.py` — endpoint: `POST /pets/{owner}/{repo}/resurrect` (thin stub; calls `PetResurrectionService` from T015)
- [ ] T010 [US1] Implement `src/github_tamagotchi/api/routes/pets_media.py` — endpoints: `GET /pets/{owner}/{repo}/badge.svg`, `GET /pets/{owner}/{repo}/image/{stage}`, `GET /pets/{owner}/{repo}/image/{stage}/animated`, `POST /pets/{owner}/{repo}/generate-images`, `POST /pets/{owner}/{repo}/regenerate-images` (thin stubs calling `PetImageService` T013 and `AnimatedGifService` T014)
- [ ] T011 [US1] Implement `src/github_tamagotchi/api/routes/social.py` — endpoints: `GET /leaderboard`, `GET /showcase/{username}.svg`, `GET /contributor/{owner}/{repo}/{username}.svg` (thin stubs calling `LeaderboardService` T017 and `ContributorBadgeService` T016)
- [ ] T012 [US1] Implement `src/github_tamagotchi/api/routes/admin.py` — endpoints: `GET /admin`, `PATCH /admin`, `DELETE /admin`, `POST /admin/contributors/exclude`, `DELETE /admin/contributors/exclude/{login}`, `POST /admin/reset` (thin stubs calling `PetAdminService` T018)
- [ ] T013 [US1] Implement `src/github_tamagotchi/api/routes/webhooks.py` — endpoint: `POST /webhooks/github` (thin stub calling `WebhookProcessorService` T019)
- [ ] T014 [US2] Update `src/github_tamagotchi/api/routes/__init__.py` to include all 9 sub-routers with their prefix/tag configuration

**Checkpoint**: All 9 domain router files exist; all 35 endpoints are declared. Routers for T009–T013 have stub handlers that will be backed by services in Phase 4.

---

## Phase 4: User Stories 3 & 4 — Orchestration Services (Priority: P1 + P2)

**Goal**: Extract business logic from the thick handler bodies in `api/routes.py` into injectable service classes. Services call existing `services/` and `crud/` files — those files are NOT modified.

**Independent Test**: Each service can be instantiated and called in a plain `pytest` unit test with mocked dependencies (no HTTP client, no database).

- [ ] T015 [P] [US4] Implement `src/github_tamagotchi/services/orchestration/pet_resurrection_service.py` — `PetResurrectionService.resurrect(pet, session, now)` — extract from `api/routes.py` lines 475–536
- [ ] T016 [P] [US4] Implement `src/github_tamagotchi/services/orchestration/contributor_badge_service.py` — `ContributorBadgeService.get_badge_svg(repo_owner, repo_name, username, github_service)` — extract from lines 1526–1593
- [ ] T017 [P] [US4] Implement `src/github_tamagotchi/services/orchestration/leaderboard_service.py` — `LeaderboardService.get_leaderboard(session)` — extract from lines 1456–1484
- [ ] T018 [P] [US4] Implement `src/github_tamagotchi/services/orchestration/pet_admin_service.py` — `PetAdminService.{get_settings, update_settings, exclude_contributor, remove_exclusion, reset_pet}` — extract from lines 1596–1872
- [ ] T019 [P] [US4] Implement `src/github_tamagotchi/services/orchestration/webhook_processor_service.py` — `WebhookProcessorService.process(payload, signature, event_type, session)` — extract from lines 1346–1437
- [ ] T020 [US4] Implement `src/github_tamagotchi/services/orchestration/pet_image_service.py` — `PetImageService.get_or_generate(repo_owner, repo_name, stage, session, storage)` — extract from lines 1007–1080
- [ ] T021 [US4] Implement `src/github_tamagotchi/services/orchestration/animated_gif_service.py` — `AnimatedGifService.get_or_generate(repo_owner, repo_name, stage, pet, session, storage)` — extract from lines 1082–1201
- [ ] T022 Update `src/github_tamagotchi/services/orchestration/__init__.py` to export all 7 service classes

**Checkpoint**: All 7 orchestration services implemented and importable.

---

## Phase 5: User Story 3 — Cutover & Behaviour Verification (Priority: P1)

**Goal**: Replace `api/routes.py` registration with the new `api/routes/` package in the main app. All 1,100+ existing tests must pass without modification.

**Independent Test**: `pytest` exits 0. No endpoint URL changes. No response body changes.

- [ ] T023 [US3] Read `src/github_tamagotchi/main.py` (or wherever `api/routes.py` is imported and mounted) to identify the exact registration point
- [ ] T024 [US3] Update the app registration in `src/github_tamagotchi/main.py` (or `api/__init__.py`) to import from `api.routes` (the new package) instead of `api.routes` (the old module) — adjust prefix/tag config to match existing URL structure
- [ ] T025 [US3] Run `pytest` against the full test suite — fix any import errors, missing re-exports, or URL mismatches revealed
- [ ] T026 [US3] Delete `src/github_tamagotchi/api/routes.py` (only after T025 passes)

**Checkpoint**: `routes.py` is gone; all existing tests pass; all 35 endpoints respond correctly.

---

## Phase 6: User Story 4 — Unit Tests for Orchestration Services (Priority: P2)

**Goal**: Each service class has ≥80% unit test coverage, testable without HTTP or real database.

**Independent Test**: `pytest tests/unit/services/orchestration/ -v` passes with ≥80% coverage per service.

- [ ] T027 [P] [US4] Write unit tests for `PetResurrectionService` in `tests/unit/services/orchestration/test_pet_resurrection_service.py`
- [ ] T028 [P] [US4] Write unit tests for `PetImageService` in `tests/unit/services/orchestration/test_pet_image_service.py`
- [ ] T029 [P] [US4] Write unit tests for `AnimatedGifService` in `tests/unit/services/orchestration/test_animated_gif_service.py`
- [ ] T030 [P] [US4] Write unit tests for `WebhookProcessorService` in `tests/unit/services/orchestration/test_webhook_processor_service.py`
- [ ] T031 [P] [US4] Write unit tests for `ContributorBadgeService` in `tests/unit/services/orchestration/test_contributor_badge_service.py`
- [ ] T032 [P] [US4] Write unit tests for `LeaderboardService` in `tests/unit/services/orchestration/test_leaderboard_service.py`
- [ ] T033 [P] [US4] Write unit tests for `PetAdminService` in `tests/unit/services/orchestration/test_pet_admin_service.py`

**Checkpoint**: All service unit tests pass; coverage ≥80% per service (SC-004).

---

## Phase 7: Polish & Success Criteria Verification

**Purpose**: Confirm all success criteria from the spec are met before merge.

- [ ] T034 Verify SC-001: `api/routes.py` deleted; count lines in each of the 9 router files — each must be ≤300 lines
- [ ] T035 Verify SC-002: Audit handler bodies in all routers — no function body exceeds 20 lines (excluding docstrings)
- [ ] T036 Verify SC-003: `pytest` full suite passes (green)
- [ ] T037 [P] Verify SC-006: `grep -r "is_admin\|is_owner\|require.*admin\|check.*admin" src/` — auth logic must appear in exactly one canonical location (`api/dependencies.py`)
- [ ] T038 [P] Run linter (`ruff check src/`) — zero errors on all new files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all domain work
- **Router Split (Phase 3)**: Depends on Phase 2 completion; T005–T008 parallelizable immediately; T009–T013 depend on Phase 4 services being complete
- **Orchestration Services (Phase 4)**: Depends on Phase 2; all 7 services are fully parallel with each other
- **Cutover (Phase 5)**: Depends on ALL of Phase 3 + Phase 4
- **Unit Tests (Phase 6)**: Depends on Phase 4; all 7 test files are parallel
- **Polish (Phase 7)**: Depends on Phase 5 + Phase 6

### Key Parallelism

Phase 3 routers for simple domains (T005–T008 — no thick business logic) and all Phase 4 orchestration services (T015–T019) can be worked simultaneously after Phase 2.

Phase 3 routers for complex domains (T009–T013) depend on their corresponding Phase 4 services:
- T009 (pets_actions) ← T015 (PetResurrectionService)
- T010 (pets_media) ← T020 + T021 (PetImageService, AnimatedGifService)
- T011 (social) ← T016 + T017 (ContributorBadgeService, LeaderboardService)
- T012 (admin) ← T018 (PetAdminService)
- T013 (webhooks) ← T019 (WebhookProcessorService)

---

## Parallel Example: Phase 4 Services

```
# All 7 services can be implemented simultaneously:
Task: T015 — services/orchestration/pet_resurrection_service.py
Task: T016 — services/orchestration/contributor_badge_service.py
Task: T017 — services/orchestration/leaderboard_service.py
Task: T018 — services/orchestration/pet_admin_service.py
Task: T019 — services/orchestration/webhook_processor_service.py
Task: T020 — services/orchestration/pet_image_service.py
Task: T021 — services/orchestration/animated_gif_service.py
```

---

## Implementation Strategy

### MVP (Stories 1–3 only — fully working refactor)

1. Phase 1: Setup directories
2. Phase 2: `dependencies.py` + read routes.py header
3. Phase 3 + Phase 4 in parallel (simple routers + all services)
4. Phase 5: Cutover + delete routes.py
5. **STOP**: Run full test suite — must be green before continuing

### Full Delivery (all stories)

6. Phase 6: Unit tests per service (SC-004)
7. Phase 7: Success criteria verification

---

## Notes

- Never modify existing `services/` or `crud/` files
- When extracting logic from `routes.py`, copy verbatim first, then slim the handler down to a pass-through call
- Commit after Phase 5 cutover passes tests — this is the safe point
- `[P]` tasks = different files, no shared state — safe to implement simultaneously
