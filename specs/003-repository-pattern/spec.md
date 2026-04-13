# Feature Specification: Repository Pattern and Exception Abstraction

**Feature Branch**: `refactor/repository-pattern`
**Created**: 2026-04-13
**Status**: Implementing

## Overview

Route handlers currently call `crud/` functions directly, and those functions let SQLAlchemy
errors propagate unhandled. There is no layer that owns the mapping between "a database uniqueness
constraint was violated" and "this means a conflict at the domain level".

This spec introduces three architectural changes:

1. **Repository layer** (`repositories/`) — all SQLAlchemy queries live here. Each repository
   function catches database exceptions and translates them into domain exceptions.

2. **Domain exception hierarchy** (`exceptions.py`) — typed errors that describe *what went wrong*
   at the domain level, not *how it went wrong* at the database level.

3. **Service layer** (`services/pet.py`, etc.) — sits between routes and repositories. Owns
   business rules. Calls repositories. May further translate or re-raise domain exceptions.
   Routes call services; services call repositories. No route touches a repository directly.

---

## Architecture

```
HTTP Request
    │
    ▼
api/routes/v1/*.py          ← HTTP only: parse request, call service, return response
    │                          catches domain exceptions via FastAPI exception handlers
    │
    ▼
services/pet.py             ← Business rules: validation, coordination, domain invariants
    │                          calls repositories; may raise NotFoundError, ConflictError, etc.
    │
    ▼
repositories/pet.py         ← Data access only: SQLAlchemy queries
                               catches SQLAlchemyError → raises RepositoryError (or subclass)
                               catches IntegrityError → raises ConflictError
                               never exposes SQLAlchemy internals to callers
```

### Exception hierarchy (`exceptions.py`)

```
AppError(Exception)
└── RepositoryError(AppError)       ← generic DB failure (wraps SQLAlchemyError)
    ├── NotFoundError               ← record does not exist
    ├── ConflictError               ← uniqueness/integrity violation
    └── ConstraintError             ← other constraint violation (FK, check, etc.)
```

Routes never import SQLAlchemy exceptions. Services never import SQLAlchemy exceptions.
Repositories import SQLAlchemy exceptions and convert them at the boundary.

### FastAPI exception handlers

Registered on the app in `main.py`:

| Domain exception | HTTP status | Response body |
|-----------------|-------------|---------------|
| `NotFoundError` | 404 | `{"detail": str(exc)}` |
| `ConflictError` | 409 | `{"detail": str(exc)}` |
| `RepositoryError` | 500 | `{"detail": "Internal error"}` (detail hidden) |

---

## User Stories

### Story 1 — Route handler contains no database knowledge (Priority: P1)

A route handler should read like a controller: get input, call service, return output. It should
not know whether the service uses Postgres, Redis, or a flat file.

**Acceptance Scenarios**:

1. **Given** any route handler, **When** a developer reads it, **Then** it contains zero
   SQLAlchemy imports, zero `session.execute` calls, and zero `pet_crud.*` calls
2. **Given** a handler that needs a pet, **When** the pet doesn't exist, **Then** the 404
   is produced by the exception handler on the app — not by an explicit `if not pet` guard
   inside the handler itself

---

### Story 2 — Repository hides all database implementation details (Priority: P1)

A service function should be able to call a repository without knowing which ORM or database
is used.

**Acceptance Scenarios**:

1. **Given** a service function, **When** a developer reads it, **Then** it imports from
   `repositories.*`, not from SQLAlchemy directly
2. **Given** a `create` call on the repository, **When** a uniqueness constraint is violated,
   **Then** the caller receives `ConflictError`, not `sqlalchemy.exc.IntegrityError`
3. **Given** any repository function, **When** a database connection fails, **Then** the caller
   receives `RepositoryError`, not a raw `sqlalchemy.exc.OperationalError`

---

### Story 3 — Exception messages are domain-readable (Priority: P2)

An error that propagates to the HTTP response body should describe what went wrong in terms of
the domain, not the database internals.

**Acceptance Scenarios**:

1. **Given** a 409 response from `POST /pets`, **When** a client inspects the detail, **Then**
   it reads `"Pet already exists for owner/repo"`, not a PostgreSQL constraint name
2. **Given** a 500 response from a repository failure, **When** a client inspects the detail,
   **Then** it reads `"Internal error"` — the SQLAlchemy message is logged but not exposed

---

## Functional Requirements

- **FR-001**: All SQLAlchemy `select`, `insert`, `update`, `delete` statements must live in
  `repositories/`. No service or route may execute raw ORM queries.
- **FR-002**: Every repository function must wrap exceptions: `IntegrityError` → `ConflictError`;
  `SQLAlchemyError` → `RepositoryError`; never let SQLAlchemy exceptions propagate to callers.
- **FR-003**: The `crud/` package must be kept as a re-export shim pointing to `repositories/`
  for backwards compatibility with existing code outside the route layer (`main.py`, `services/
  webhook.py`, `api/auth.py`, `mcp/server.py`) and with existing test imports.
- **FR-004**: No route handler may import from `repositories/` or `crud/` directly — only from
  `services/`.
- **FR-005**: `api/dependencies.py`'s `get_pet_or_404` becomes a service call; `NotFoundError`
  is raised by the service, not by a guard in `dependencies.py`.
- **FR-006**: FastAPI exception handlers for `NotFoundError`, `ConflictError`, and
  `RepositoryError` must be registered on the app.
- **FR-007**: All 1121+ existing tests must pass. Repository renaming is transparent via the
  `crud/` shim layer; domain exception types must produce the same HTTP status codes as before.

---

## Repository Design

Each repository module exposes async functions (not classes). The session is always the first
parameter so callers can participate in a shared transaction.

```python
# Pattern for every repository function
async def create(db: AsyncSession, ...) -> ModelType:
    try:
        obj = ModelType(...)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("...") from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise RepositoryError("...") from exc
```

---

## Service Design

Services are modules of async functions (not classes for this scale). Each function:
- Takes `db: AsyncSession` as its first parameter
- Calls one or more repository functions
- Contains domain logic (validation, calculations, invariants)
- May call `services/pet_logic.py` for pure computations
- May raise domain exceptions (`NotFoundError`, `ConflictError`) — never raises `HTTPException`

```python
# services/pet.py
async def get_or_raise(db: AsyncSession, owner: str, repo: str) -> Pet:
    pet = await pet_repo.get_by_repo(db, owner, repo)
    if pet is None:
        raise NotFoundError(f"Pet not found for {owner}/{repo}")
    return pet
```

---

## Backwards Compatibility

`crud/` stays as re-export shims:
```python
# crud/pet.py
from github_tamagotchi.repositories.pet import (
    create_pet, get_pet_by_repo, get_pets, ...
)
```

This preserves:
- `from github_tamagotchi.crud import pet as pet_crud` in non-route code
- Direct test imports like `from github_tamagotchi.crud.pet import _leaderboard_cache`
- `services/webhook.py` and `main.py` which are out of scope for this refactor

---

---

## Schema Layer (Request/Response DTOs)

Pydantic `BaseModel` classes are currently defined inline inside router files. This makes them
invisible to the rest of the app, hard to share, and forces a developer to read route code to
understand what the API sends and receives.

All request and response models move to a `schemas/` package:

```
src/github_tamagotchi/schemas/
├── __init__.py
├── pets.py       ← PetCreate, PetResponse, PetListResponse, FeedResponse,
│                   StyleUpdateRequest, PetRenameRequest, BadgeStyleUpdateRequest,
│                   SkinInfo, SkinSelectRequest, SkinSelectResponse,
│                   ImageGenerationResponse
├── social.py     ← LeaderboardEntry, LeaderboardCategory, LeaderboardResponse
├── admin.py      ← PetAdminSettingsUpdate, ExcludedContributorItem, PetAdminResponse
└── info.py       ← PetCharacteristics, CommentResponse, CommentsListResponse,
                    CommentCreate, AchievementItem, AchievementsResponse,
                    MilestoneItem, MilestonesResponse, ContributorRelationshipItem,
                    ContributorRelationshipsResponse, BlameEntryItem, HeroEntryItem,
                    BlameBoardResponse
```

Route handlers import schemas from `schemas.*`, not define them inline. Router files contain
only: imports, a router instance, and handler functions.

---

## Out of Scope

- Refactoring `services/webhook.py` (complex, has its own DB access patterns)
- Refactoring `main.py` page routes (HTML routes, separate concern)
- Refactoring `mcp/server.py`
- Making `api/auth.py` use the service layer (identity/session concern, low value)
- Class-based repositories (overkill at this scale; module functions are idiomatic in FastAPI)
- Unit testing repositories in isolation with mocked DB sessions (integration tests already cover this)
