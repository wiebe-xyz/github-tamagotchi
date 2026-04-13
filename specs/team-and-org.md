# Feature Specification: Team and Org
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Contributors are first-class citizens. The system tracks each contributor's activity score, standing, recent deeds, and sins — and surfaces this on a blame board and heroes board. Dashboard and org-level views let users see all pets they have contributed to. Contributor badges can be embedded per-user.

## User Stories

### Blame board shows who hurt the pet (Priority: P2)
The blame board attributes specific repo health problems to contributors.
**Acceptance Scenarios**:
1. Given a PR has been open for > 48 hours, When the blame board is fetched, Then the contributor who opened it appears as a blame entry
2. Given blame_board_enabled == False, When the blame board API is called, Then it returns an empty blame_entries list
3. Given the repo is healthy, Then blame_entries is empty and hero_entries shows recent positive activity

### Contributors are scored and ranked (Priority: P2)
Each contributor has a score computed from 30-day commits and merged PRs.
**Acceptance Scenarios**:
1. Given a contributor with 5 commits and 2 merged PRs in 30 days, Then score = 5*5 + 2*10 = 45
2. Given a contributor's score >= 50 AND they are the top scorer, Then standing = "favorite"
3. Given a contributor inactive for >= 30 days, Then standing = "absent"
4. Given a contributor's score < 0, Then standing = "doghouse"

### User dashboard shows all their pets (Priority: P2)
A user can see all repositories they have contributed to that have pets registered.
**Acceptance Scenarios**:
1. Given a logged-in user visits /dashboard/{username}, Then all pets associated with repos they contribute to are listed
2. Given a user has no associated pets, Then an empty state is shown

### Org view aggregates all org pets (Priority: P2)
An organization's pets can be viewed collectively.
**Acceptance Scenarios**:
1. Given repos under org "my-org" have pets, When /org/my-org is visited, Then all those pets are shown
2. Given some repos have no pets, Then they do not appear in the org view

### Contributor badges are embeddable (Priority: P3)
Each contributor can embed a badge showing their standing across repos.
**Acceptance Scenarios**:
1. Given contributor "alice" has a standing of "favorite" on a repo, When a badge is fetched for alice, Then it reflects her standing
2. Given contributor_badges_enabled == False on a pet, Then no contributor badge is served for that pet

## Functional Requirements
- **FR-001**: ContributorRelationship model: github_username, standing, score, last_activity, good_deeds (list), sins (list)
- **FR-002**: Score formula: commits_30d * 5 + merged_prs_30d * 10
- **FR-003**: Standings: favorite (top scorer, score >= 0, active), good (score >= 50, active), neutral (default active), doghouse (score < 0), absent (inactive >= 30 days or no activity)
- **FR-004**: GOOD_SCORE_THRESHOLD = 50, ABSENT_DAYS_THRESHOLD = 30
- **FR-005**: MAX_RECENT_EVENTS = 5 (max items in good_deeds and sins lists per contributor)
- **FR-006**: Blame board: lists blame_entries (issue, culprit, how_long) and hero_entries (good_deed, hero, when)
- **FR-007**: `blame_board_enabled` on Pet (default True); when False, blame_entries and hero_entries are empty
- **FR-008**: `contributor_badges_enabled` on Pet (default True); when False, contributor badge endpoints return 404 or empty
- **FR-009**: ExcludedContributor model allows repo owners to exclude specific GitHub logins from all contributor calculations
- **FR-010**: Contributor data updated on every poll cycle via `build_contributor_updates()` and `upsert_contributor_relationship()`

## Technical Notes
- Key files: `src/github_tamagotchi/services/contributor_relationships.py`, `src/github_tamagotchi/crud/contributor_relationship.py`, `src/github_tamagotchi/models/contributor_relationship.py`, `src/github_tamagotchi/models/excluded_contributor.py`
- `ContributorStanding` enum: FAVORITE, GOOD, NEUTRAL, DOGHOUSE, ABSENT
- `calculate_score(commits_30d, merged_prs_30d)` returns int
- `calculate_standing(score, is_top_scorer, last_activity, now)` returns standing string
- `build_contributor_updates()` takes `AllContributorActivity` from GitHub service and returns `list[ContributorUpdate]`
- Dashboard and org routes are HTML pages served by Jinja2 templates in main.py

## Success Criteria
- SC-001: Contributor standings update within one poll cycle after repo activity changes
- SC-002: Blame board correctly attributes open PRs and stale issues to responsible contributors
- SC-003: Excluded contributors do not appear on blame board or in contributor score calculations
- SC-004: Org view loads all pets for repos under a given GitHub organization
