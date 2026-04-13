# Feature Specification: Pet Lifecycle
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Each registered repository gets a virtual pet that evolves through six stages as the repository accumulates activity. The pet's mood reflects the current state of the repo in real time, updated on every poll cycle (default every 30 minutes). Health and experience are the two key numeric dimensions.

## User Stories

### Egg hatches when commits begin (Priority: P1)
A newly registered repository starts as an EGG. Once enough experience accumulates (100 XP), it hatches into a BABY.
**Acceptance Scenarios**:
1. Given a newly registered repo with 0 XP, When the poll runs and finds a recent commit, Then the pet gains 20 XP
2. Given a pet at EGG stage with 100 XP, When `get_next_stage` is called, Then it returns BABY
3. Given a pet at BABY stage, When the badge endpoint is called, Then the badge shows the baby emoji

### Pet evolves through all six stages (Priority: P1)
XP accumulates and triggers stage transitions automatically.
**Acceptance Scenarios**:
1. Given XP thresholds EGG=0, BABY=100, CHILD=500, TEEN=1500, ADULT=5000, ELDER=15000
2. Given a pet with 4999 XP at TEEN, When it gains enough XP to cross 5000, Then stage becomes ADULT and an evolution milestone is recorded
3. Given a pet already at ELDER, When `get_next_stage` is called, Then it stays ELDER

### Mood reflects repo health (Priority: P1)
The pet's mood updates each poll cycle based on repo metrics.
**Acceptance Scenarios**:
1. Given health == 0, Then mood is SICK regardless of other signals
2. Given critical or high security alerts > 0, Then mood is SICK
3. Given stale dependencies, Then mood is SICK
4. Given no commit in > 3 days (HUNGRY_THRESHOLD_DAYS), Then mood is HUNGRY
5. Given oldest PR open > 48 hours, Then mood is WORRIED
6. Given oldest issue unanswered > 7 days OR contributor_count == 1, Then mood is LONELY
7. Given last CI success and none of the above, Then mood is DANCING
8. Given health >= 80 and none of the above, Then mood is HAPPY
9. Otherwise mood is CONTENT

## Functional Requirements
- **FR-001**: Six stages: EGG, BABY, CHILD, TEEN, ADULT, ELDER
- **FR-002**: XP thresholds: EGG=0, BABY=100, CHILD=500, TEEN=1500, ADULT=5000, ELDER=15000
- **FR-003**: XP per poll: +20 if commit within 24h, +10 if last CI success
- **FR-004**: Seven moods: HAPPY, CONTENT, HUNGRY, WORRIED, LONELY, SICK, DANCING
- **FR-005**: Mood priority order (highest to lowest): SICK > HUNGRY > WORRIED > LONELY > DANCING > HAPPY > CONTENT
- **FR-006**: Health delta applied each poll; clamped to [0, 100]
- **FR-007**: Health starts at 100 for new pets
- **FR-008**: Stage transitions recorded as milestones with old_stage, new_stage, XP, age_days
- **FR-009**: HUNGRY_THRESHOLD_DAYS, PR_REVIEW_SLA_HOURS, ISSUE_RESPONSE_SLA_DAYS are admin-configurable per pet (defaults: 3, 48, 7)

## Technical Notes
- Key files: `src/github_tamagotchi/services/pet_logic.py`, `src/github_tamagotchi/models/pet.py`
- `calculate_mood(health, current_health)` returns PetMood
- `get_next_stage(current_stage, experience)` returns PetStage
- `calculate_experience(health)` returns int delta
- `calculate_health_delta(health)` returns int delta (can be negative)
- Evolution check runs inside the poll loop in `main.py:poll_repositories()`
- `PetStage` and `PetMood` are `StrEnum` — stored as lowercase strings in DB

## Success Criteria
- SC-001: All 6 stages are reachable via normal repo activity
- SC-002: Mood changes are visible on the badge/GIF within one poll cycle
- SC-003: Evolution milestone records are created at each stage transition
- SC-004: Health never goes below 0 or above 100
