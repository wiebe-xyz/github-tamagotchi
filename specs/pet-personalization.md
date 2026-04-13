# Feature Specification: Pet Personalization
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Pets have a rich set of personalization options: a name, a visual style, a badge style, unlockable skins, and a deterministic personality. Repo owners control these settings. Some options unlock through earned milestones. Owners can also exclude specific contributors from activity calculations.

## User Stories

### Pet is automatically named on creation (Priority: P1)
A name is auto-generated from the repository name at creation time.
**Acceptance Scenarios**:
1. Given repo_name="my-awesome-project", When a pet is created without an explicit name, Then generate_name_from_repo produces a name
2. Given an explicit name is provided, Then it is validated (1-20 chars) and used as-is
3. Given an invalid name (empty or > 20 chars), Then the API returns 422

### Owner can rename their pet (Priority: P2)
Repo owners can change the pet's display name at any time.
**Acceptance Scenarios**:
1. Given an authenticated owner, When they POST to /api/v1/pets/{id}/rename with a valid name, Then the pet's name updates
2. Given a name longer than 20 characters, Then the API returns 422

### Pet has a deterministic personality (Priority: P2)
Five personality traits are derived from the repo identity hash, with nudges from actual repo health.
**Acceptance Scenarios**:
1. Given the same owner/repo, When generate_personality is called twice, Then the base trait values are identical
2. Given recent commits (< 24h), When generate_personality is called with health, Then the activity trait is nudged toward 1.0
3. Given open_issues_count > 10, Then the tidiness trait is nudged toward 0.0
4. Traits: activity, sociability, bravery, tidiness, appetite — all in range [0.0, 1.0]

### Visual style can be changed (Priority: P2)
Owners can select from 5 visual styles that change the AI art direction.
**Acceptance Scenarios**:
1. Given an owner visits pet settings, When they change style to "doom_metal", Then new images are queued with the new style
2. Given an invalid style key, Then the API returns 422
3. Available styles: kawaii (default), doom_metal, wizard, retro_scifi, minimalist

### Skins unlock through milestones (Priority: P2)
Additional skins become available when certain conditions are met.
**Acceptance Scenarios**:
1. Given a pet reaches ADULT stage, Then the ROBOT skin is unlocked
2. Given a pet reaches ELDER stage, Then the DRAGON skin is also unlocked
3. Given a pet has recovered from critical health (<5) three times (low_health_recoveries >= 3), Then the GHOST skin unlocks
4. Given the CLASSIC skin, Then it is always available (default)

### Owner can opt out of leaderboard (Priority: P2)
Repo owners can hide their pet from all leaderboard categories.
**Acceptance Scenarios**:
1. Given leaderboard_opt_out == True, When the leaderboard is fetched, Then this pet does not appear
2. Given leaderboard_opt_out == False (default), Then the pet appears on applicable leaderboard categories

### Owner can exclude contributors (Priority: P2)
Bots and inactive accounts can be excluded from contributor-based metrics.
**Acceptance Scenarios**:
1. Given a repo owner adds "dependabot[bot]" to excluded contributors, Then that contributor is excluded from the blame board and activity metrics
2. Given a contributor is excluded, Then their commits do not affect contributor_count bonuses

## Functional Requirements
- **FR-001**: Name: 1-20 characters, validated with `is_valid_pet_name()`, auto-generated via `generate_name_from_repo()` if not provided
- **FR-002**: 5 personality traits stored as floats [0.0, 1.0] on the Pet model; generated once at creation, nudged by health metrics
- **FR-003**: Personality hash seed: SHA-256 of `{owner}/{repo}`, base values from first 5 × 8-char hex chunks
- **FR-004**: 4 skins: CLASSIC (always), ROBOT (Adult+), DRAGON (Elder), GHOST (3x low-health recoveries)
- **FR-005**: `low_health_recoveries` counter increments when health recovers from below 5
- **FR-006**: `get_unlocked_skins(pet)` returns the list of currently unlocked PetSkin variants
- **FR-007**: Badge styles: playful (default), minimal, maintained — stored as `badge_style` on Pet
- **FR-008**: Visual styles stored as `style` field on Pet; changing style triggers image regeneration
- **FR-009**: `leaderboard_opt_out` boolean field (default False); excludes pet from all leaderboard categories
- **FR-010**: `blame_board_enabled` and `contributor_badges_enabled` booleans allow per-pet opt-out by repo admin
- **FR-011**: `ExcludedContributor` model with repo_owner, repo_name, github_username; CASCADE delete on pet deletion

## Technical Notes
- Key files: `src/github_tamagotchi/services/pet_logic.py` (personality, skins), `src/github_tamagotchi/services/naming.py`, `src/github_tamagotchi/services/badge.py`, `src/github_tamagotchi/models/excluded_contributor.py`
- `PetSkin` is a StrEnum: CLASSIC, ROBOT, DRAGON, GHOST
- `SKIN_UNLOCK_CONDITIONS` dict maps PetSkin to human-readable condition string
- Badge styles affect SVG layout/color scheme only, not the sprite image

## Success Criteria
- SC-001: The same repo always produces the same personality traits regardless of when pets are created
- SC-002: Skins unlock automatically when conditions are met (checked on poll cycle)
- SC-003: Leaderboard opt-out takes effect on the next leaderboard refresh
- SC-004: Excluded contributors do not affect blame board or contributor count metrics
