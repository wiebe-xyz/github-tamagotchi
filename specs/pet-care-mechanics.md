# Feature Specification: Pet Care Mechanics
**Status**: Implemented
**Created**: 2026-09-04

## Overview
A mood/display-only layer on top of the core health/XP/evolution system. Four independent signals — mess (from feeding), boredom (from lack of play), neglect-hunger (from not being fed), and a day/night sleep cycle — combine into the pet's mood alongside the existing repo-health-driven mood. None of this affects health, XP, or evolution: those stay driven entirely by real repo activity via `update_pet_from_repo`, exactly as before. This mirrors the existing weight mechanic (`services/pet_feeding.py`) — a second, cosmetic dimension layered on top of the real progress system.

## User Stories

### Feeding leaves a mess that needs cleaning (Priority: P1)
Each `feed_pet` call adds to the pet's mess level. Once it crosses a threshold the pet is visibly dirty until cleaned.
**Acceptance Scenarios**:
1. Given a clean pet, When `feed_pet` is called, Then `mess_level` increases by 1
2. Given `mess_level >= MESS_DIRTY_THRESHOLD` (3), Then the pet's mood is DIRTY (unless SICK or SLEEPING take priority)
3. Given a dirty pet, When `clean_pet` is called, Then `mess_level` resets to 0, `last_cleaned_at` is recorded, and the amount cleared is returned
4. Given a pet whose mood was DIRTY, When `clean_pet` clears the mess, Then mood resets to CONTENT

### Neglecting play makes a pet lonely (Priority: P1)
Boredom is tracked independently of mood-affecting repo signals — it decays based on real-world time since the pet was last played with, scaled by the pet's `activity` personality trait.
**Acceptance Scenarios**:
1. Given a pet never played with, When less time has passed than its boredom threshold since `created_at`, Then it is not bored (hatching grace period)
2. Given hours since `last_played_at` (or `created_at` if never played) exceeds `boredom_threshold_hours(activity)`, Then the pet is bored and its mood is LONELY
3. Given `activity=1.0` (active), Then the threshold is `BOREDOM_MIN_HOURS` (12h); given `activity=0.0` (lazy), Then it's `BOREDOM_MAX_HOURS` (96h), linearly interpolated in between
4. Given `play_with_pet` is called while awake, Then `last_played_at` updates unconditionally — even if the mood-nudge itself is on cooldown, a visit still counts against boredom

### Not feeding a pet makes it hungry, independent of repo activity (Priority: P1)
A second, independent hunger signal from `feed_pet` neglect — distinct from the existing repo-inactivity hunger check in `calculate_mood` (`HUNGRY_THRESHOLD_DAYS`, based on `last_commit_at`), which is untouched.
**Acceptance Scenarios**:
1. Given a pet never fed, When less time has passed than its threshold since `created_at`, Then it is not neglect-hungry (hatching grace period)
2. Given hours since `last_fed_at` (or `created_at` if never fed) exceeds `neglect_hunger_threshold_hours(appetite)`, Then the pet's mood is HUNGRY
3. Given `appetite=1.0` ("Hungry" trait), Then the threshold is `NEGLECT_HUNGER_MIN_HOURS` (24h); given `appetite=0.0` (light eater), Then it's `NEGLECT_HUNGER_MAX_HOURS` (120h), linearly interpolated in between

### Pets sleep overnight (Priority: P1)
A pure function of wall-clock time — no persisted state, no personality input. Sleep gates `feed_pet` and `play_with_pet`, but never `clean_pet` or read-only tools.
**Acceptance Scenarios**:
1. Given the UTC hour is in `[22:00, 24:00)` or `[0:00, 07:00)`, Then the pet is asleep and its mood is SLEEPING (unless SICK)
2. Given `feed_pet` is called while asleep, Then no mutation happens at all — no mess added, no weight/health change, `last_fed_at` untouched — and the response says so
3. Given `play_with_pet` is called while asleep, Then no mood nudge and no `last_played_at` update happen, and the response includes the pet's ASCII art plus an explanatory message
4. Given `clean_pet` is called while asleep, Then it still works exactly as it would while awake

### Mood priority order (Priority: P1)
`calculate_mood_with_care` layers the four signals above onto the existing `calculate_mood` base result.
**Acceptance Scenarios**:
1. Given the base mood (from `calculate_mood`) is SICK, Then the result is SICK regardless of any care signal — a sick pet doesn't sleep peacefully or notice mess
2. Otherwise, in order, first match wins: asleep -> SLEEPING, dirty -> DIRTY, neglect-hungry -> HUNGRY, bored -> LONELY
3. Given none of the above fire, Then the base mood from `calculate_mood` is returned unchanged

## Functional Requirements
- **FR-001**: `mess_level` (int, default 0) and `last_cleaned_at` columns on `Pet`; `MESS_PER_FEED=1`, `MESS_DIRTY_THRESHOLD=3`
- **FR-002**: `last_played_at` column on `Pet`; boredom thresholds `BOREDOM_MAX_HOURS=96` (activity=0.0) to `BOREDOM_MIN_HOURS=12` (activity=1.0), linear interpolation, activity clamped to [0,1]
- **FR-003**: Neglect-hunger reuses the existing `last_fed_at` column (no new column); thresholds `NEGLECT_HUNGER_MAX_HOURS=120` (appetite=0.0) to `NEGLECT_HUNGER_MIN_HOURS=24` (appetite=1.0), linear interpolation, appetite clamped to [0,1]
- **FR-004**: Sleep window is `[SLEEP_START_HOUR_UTC=22, SLEEP_END_HOUR_UTC=7)` UTC, wrapping midnight; no persisted state
- **FR-005**: Two new moods: SLEEPING, DIRTY (`PetMood` enum, 9 total)
- **FR-006**: `calculate_mood_with_care(health, pet, personality, now)` priority order: SICK (from base) > SLEEPING > DIRTY > HUNGRY (neglect) > LONELY (bored) > base mood unchanged
- **FR-007**: `feed_pet` and `play_with_pet` are both no-ops while asleep (no DB mutation); `clean_pet` is always allowed
- **FR-008**: New MCP tool `clean_pet(repo_owner, repo_name)` — clears mess, resets DIRTY mood to CONTENT if applicable, returns amount cleared + pet status + ASCII art
- **FR-009**: Health, XP, and evolution are never affected by any care mechanic — they remain driven solely by real repo activity via `update_pet_from_repo`

## Technical Notes
- Key files: `src/github_tamagotchi/services/pet_care/{mess,boredom,neglect_hunger,sleep}.py`, `src/github_tamagotchi/services/pet_logic.py` (`calculate_mood_with_care`), `src/github_tamagotchi/mcp/server.py`
- Each `pet_care` module follows the established pattern from `services/pet_feeding.py`: small pure-ish functions that mutate a passed-in `Pet` in place, with the caller committing
- `update_pet_from_repo` calls `calculate_mood_with_care` instead of the base `calculate_mood`; personality is fetched earlier in the function (previously fetched only for the response message) so it's available for the mood calculation
- The mess/boredom/neglect-hunger/sleep fields are intentionally **not** mirrored into the public API's `PetResponse` schema, matching the existing precedent set by `weight` (also MCP-only, cosmetic, and absent from `PetResponse`) — the public site's health/XP/mood story stays about real repo activity; care-mechanic detail is an MCP-only layer for whoever is actively chatting with the pet. `PetResponse.mood` will still surface `"sleeping"`/`"dirty"` values automatically once the pet is polled, since `PetMood` itself gained those members.

## Success Criteria
- SC-001: None of health, XP, or evolution ever change as a result of mess, boredom, neglect-hunger, or sleep
- SC-002: A freshly hatched pet gets a grace period before boredom or neglect-hunger can fire (measured from `created_at`, not instant)
- SC-003: `clean_pet` works identically whether the pet is asleep or awake
- SC-004: `feed_pet`/`play_with_pet` while asleep never mutate the pet
