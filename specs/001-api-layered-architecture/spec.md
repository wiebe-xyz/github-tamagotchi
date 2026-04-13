# Feature Specification: API Layered Architecture

**Feature Branch**: `feature/health-metrics-clean`
**Created**: 2026-04-13
**Status**: Implemented

## Overview

The entire API lives in a single 1,872-line file (`api/routes.py`). Business logic, data access, storage orchestration, and HTTP concerns are all mixed together. This makes the codebase increasingly hard to navigate, test, and change — adding a feature or fixing a bug requires understanding a sprawling monolith.

This feature restructures the API codebase so that:
- HTTP handlers only handle HTTP (parse request, call one service, return response)
- Business logic lives in focused, domain-scoped service classes
- All existing API behaviour is preserved exactly

---

## User Stories

### Story 1 — Developer can navigate to relevant code in seconds (Priority: P1)

A developer who needs to change how pet resurrection works should be able to open the project, navigate directly to `PetResurrectionService`, read the logic, and make their change — without scrolling through 1,800 lines of unrelated endpoint code.

**Why this priority**: Developer velocity is directly gated on navigability. This is the core value of the refactor.

**Independent Test**: Given the refactored codebase, a developer unfamiliar with the project can locate the business logic for any of the 10 major domains (images, resurrection, webhooks, badges, etc.) in under 30 seconds.

**Acceptance Scenarios**:

1. **Given** the refactored codebase, **When** a developer searches for "resurrection", **Then** they find `PetResurrectionService` with all resurrection logic self-contained in it
2. **Given** the refactored codebase, **When** a developer opens the image endpoint handler, **Then** it contains only request parsing and a single service call — no storage access, no generation logic
3. **Given** any HTTP handler in the refactored code, **When** a developer reads it, **Then** they can understand its full behaviour in under 10 lines

---

### Story 2 — Developer can add a new endpoint without touching unrelated code (Priority: P1)

Adding a new pet action (e.g., "pet takes a nap") should mean creating a handler in the relevant domain router and a method on the relevant service. No other files should need editing.

**Why this priority**: Open/closed principle. Today, every new endpoint lands in a single file that becomes harder to review with each addition.

**Independent Test**: A new endpoint can be added to the pets actions domain by editing exactly two files (router + service). No changes required in any other file.

**Acceptance Scenarios**:

1. **Given** the refactored routers, **When** a new endpoint is added to the pets-actions domain, **Then** only `api/pets_actions.py` and `services/pet_action_service.py` need to change
2. **Given** the refactored routers, **When** a developer looks at `api/pets_media.py`, **Then** they see only image/GIF/badge endpoints — nothing unrelated

---

### Story 3 — All existing API behaviour is preserved exactly (Priority: P1)

Every consumer of the API — the web UI, external badge embeds, MCP tools, webhooks — must continue working without any changes.

**Why this priority**: This is a refactor, not a rewrite. Zero regressions is non-negotiable.

**Independent Test**: The full existing test suite (1,100+ tests) passes without modification after the refactor.

**Acceptance Scenarios**:

1. **Given** the refactored codebase, **When** the test suite runs, **Then** all tests pass
2. **Given** any existing API endpoint URL, **When** called with the same request, **Then** the response is byte-for-byte identical to the pre-refactor response
3. **Given** the refactored code, **When** a developer checks all route paths, **Then** every path from the original `routes.py` is still registered at the same URL

---

### Story 4 — Services are independently testable without HTTP (Priority: P2)

A developer can write a unit test for `PetImageService.get_or_generate()` without spinning up an HTTP server or making real network calls.

**Why this priority**: Enables faster, more targeted tests that don't depend on FastAPI internals.

**Independent Test**: Each new service class can be instantiated and tested in a plain Python unit test with mocked dependencies, no HTTP client needed.

**Acceptance Scenarios**:

1. **Given** `PetResurrectionService`, **When** a unit test calls `resurrect()` with a mock session and mock pet, **Then** the test can verify all business logic outcomes without touching HTTP
2. **Given** any service class, **When** its dependencies are injected or mocked, **Then** its methods can be called directly in tests

---

### Story 5 — Admin permission checking is not duplicated (Priority: P2)

Today, "require repo owner" and "require system admin" checks are scattered across endpoints. After the refactor, these checks live in one place and are reused by all endpoints that need them.

**Why this priority**: DRY principle. Duplicated auth logic is a security risk — a fix in one place won't propagate.

**Independent Test**: A search of the codebase for repo-owner auth logic returns exactly one canonical location, not multiple copies.

**Acceptance Scenarios**:

1. **Given** the refactored code, **When** a developer searches for repo admin verification logic, **Then** it exists in exactly one place
2. **Given** an admin endpoint handler, **When** a developer reads it, **Then** the auth check is a one-line reuse, not inline logic

---

## Filesystem Layout

The router package mirrors the URL hierarchy:

```
src/github_tamagotchi/api/
├── dependencies.py                  # Shared FastAPI dependency helpers (get_pet_or_404)
└── routes/
    ├── __init__.py                  # Aggregates all routers; re-exports patchable symbols
    └── v1/
        ├── __init__.py
        ├── admin.py                 # /api/v1/admin/... (pet owner config, exclusions, reset)
        ├── social.py                # /api/v1/... (leaderboard, showcase, contributor badge)
        ├── system.py                # /api/v1/... (styles, badge-styles, health, queue stats)
        ├── webhooks.py              # /api/v1/webhook (GitHub webhook receiver)
        └── pets/
            ├── __init__.py
            ├── actions.py           # /api/v1/pets/... (resurrect)
            ├── appearance.py        # /api/v1/pets/... (name, style, badge-style, skins)
            ├── crud.py              # /api/v1/pets/... (create, read, delete, feed, my-pets)
            ├── info.py              # /api/v1/pets/... (characteristics, comments, achievements)
            └── media.py             # /api/v1/pets/... (badge SVG, images, animated GIFs)
```

### Patch-compatibility pattern

Tests patch `github_tamagotchi.api.routes.settings`, `.GitHubService`, `.decrypt_token`, etc.
Sub-modules preserve this by doing:

```python
import github_tamagotchi.api.routes as _api_routes
# then at call-time: _api_routes.settings.minio_endpoint
```

`routes/__init__.py` must re-export all patchable symbols **before** importing sub-modules
so they exist on the partially-initialised package object. Import order is protected by
`# ruff: noqa: I001` at the top of `__init__.py`.

---

## Functional Requirements

- **FR-001**: All 35 existing API endpoints MUST remain accessible at their original URL paths
- **FR-002**: All existing request and response shapes MUST remain unchanged
- **FR-003**: `api/routes.py` MUST be split into domain-scoped router files under `api/routes/v1/`, with pets sub-modules nested under `v1/pets/`
- **FR-004**: Each HTTP handler MUST contain no business logic — only request parsing, a service call, and response construction
- **FR-005**: Business logic extracted from handlers MUST live in new domain-scoped service classes (not added to existing services)
- **FR-006**: New service classes MUST be independently injectable/mockable (constructor or parameter injection)
- **FR-007**: Existing `services/` files MUST NOT be modified — new service layer calls into them
- **FR-008**: Existing `crud/` files MUST NOT be modified
- **FR-009**: Admin permission checks (repo owner, system admin) MUST be consolidated into a single reusable location
- **FR-010**: The full test suite MUST pass after the refactor with no test modifications
- **FR-011**: New service classes MUST have test coverage (unit tests, not integration tests)

## Key Entities

- **Domain Router**: A FastAPI `APIRouter` scoped to a single domain (e.g., pets media, social, admin). Registered on the main app. Contains only HTTP handler functions.
- **Orchestration Service**: A class encapsulating business logic for a domain. Called by handlers, calls existing services/crud/storage. Examples: `PetImageService`, `PetResurrectionService`, `WebhookProcessorService`.
- **Existing Service**: Files already in `services/` (pet_logic, badge, github, storage, etc.). Not modified — only called by new orchestration services.
- **CRUD Layer**: Files in `crud/` (pet, user, milestone, contributor_relationship). Not modified — called by services.

## Success Criteria

- **SC-001**: `api/routes.py` is deleted; its endpoints are distributed across 9 router files under `api/routes/v1/` (pets sub-modules in `v1/pets/`), each ≤300 lines
- **SC-002**: No HTTP handler function body exceeds 20 lines (excluding docstrings and comments)
- **SC-003**: All 1,100+ existing tests pass without modification
- **SC-004**: New service classes have unit test coverage ≥80%
- **SC-005**: A developer unfamiliar with the project can locate business logic for any domain in ≤30 seconds
- **SC-006**: Admin permission logic appears in exactly one place in the codebase

## Assumptions

- The refactor is backend-only — no frontend, template, or infrastructure changes
- FastAPI dependency injection (`Depends(...)`) is the established pattern and will be preserved
- The existing `main.py` page handlers (HTML routes) are out of scope — only `api/routes.py`
- Test infrastructure (conftest, fixtures) will not need changes beyond importing from new locations
- The SQLAlchemy `AsyncSession` dependency injection pattern is preserved as-is
