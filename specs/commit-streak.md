# Feature Specification: Commit Streak
**Status**: Implemented
**Created**: 2026-04-13

## Overview
The commit streak tracks consecutive calendar days with at least one commit. It is displayed on pet profiles and badges as a motivational metric. The streak is bounded by the pet's age to prevent historical inflation.

## User Stories

### Streak increments once per calendar day (Priority: P1)
Multiple poll cycles in the same day should not inflate the streak.
**Acceptance Scenarios**:
1. Given last_streak_date is today and a new commit is detected, When update_commit_streak runs, Then commit_streak is unchanged
2. Given last_streak_date is yesterday and a commit is detected today, When update_commit_streak runs, Then commit_streak increments by 1 and last_streak_date updates to now
3. Given last_streak_date is 3 days ago and a commit is detected today, When update_commit_streak runs, Then commit_streak resets to 1

### 48-hour window tolerates polling gaps (Priority: P1)
Commits detected within 48 hours count as "recent" to tolerate midnight-boundary polling gaps.
**Acceptance Scenarios**:
1. Given last_commit_at is 47 hours ago, When update_commit_streak runs, Then the commit is counted as recent
2. Given last_commit_at is 49 hours ago, When update_commit_streak runs, Then the commit is NOT counted as recent and the streak may break

### Streak breaks when no recent activity (Priority: P1)
If more than 1 calendar day passes since the last streak date with no recent commit, the streak resets.
**Acceptance Scenarios**:
1. Given last_streak_date is 2 days ago and last_commit_at is 72+ hours ago, When update_commit_streak runs, Then commit_streak = 0
2. Given last_streak_date is None and no commit, Then commit_streak remains 0

### Streak is capped by pet age (Priority: P2)
A streak cannot exceed the number of days the pet has existed, preventing inflated values.
**Acceptance Scenarios**:
1. Given a pet created 10 days ago with commit_streak = 15, When update_commit_streak runs, Then commit_streak is capped to 10
2. Given longest_streak > age_days, Then longest_streak is also capped to age_days

### HUNGRY mood triggers after 3 days without commits (Priority: P1)
The HUNGRY_THRESHOLD_DAYS constant (default 3) determines when no-commit state causes HUNGRY mood.
**Acceptance Scenarios**:
1. Given days_since_commit > 3, When calculate_mood runs, Then mood is HUNGRY
2. Given days_since_commit == 2, When calculate_mood runs, Then HUNGRY does not trigger from this condition alone

## Functional Requirements
- **FR-001**: Streak is measured in calendar days (date comparison, not hours)
- **FR-002**: A 48-hour window is used to decide if last_commit_at counts as "recent" for the current poll cycle
- **FR-003**: At most one streak increment per calendar day (deduplication by last_streak_date.date())
- **FR-004**: A gap of 2+ calendar days resets commit_streak to 1 (not 0) if a fresh commit is present
- **FR-005**: No recent commit AND last_streak_date more than 1 day ago resets streak to 0
- **FR-006**: commit_streak and longest_streak are both capped to `max(1, (today - created_at.date()).days + 1)`
- **FR-007**: longest_streak tracks the historical maximum; never decreases except for the age cap
- **FR-008**: HUNGRY_THRESHOLD_DAYS is configurable per pet (default 3, stored as `hungry_after_days`)
- **FR-009**: Streak fields: commit_streak (current), longest_streak (max ever), last_streak_date (timestamp)

## Technical Notes
- Key files: `src/github_tamagotchi/services/pet_logic.py` (`update_commit_streak`), `src/github_tamagotchi/models/pet.py`
- `update_commit_streak(pet, health, now)` is called inside the poll loop after health update
- Age cap formula: `age_days = max(1, (now.date() - pet.created_at.date()).days + 1)`
- The HUNGRY mood uses `days_since_commit` (float) vs HUNGRY_THRESHOLD_DAYS, checked in `calculate_mood()`
- Note: the global `HUNGRY_THRESHOLD_DAYS = 3` in pet_logic.py is the system default; per-pet override is `pet.hungry_after_days`

## Success Criteria
- SC-001: A repo with daily commits shows an incrementing streak visible on the profile
- SC-002: Two poll cycles in the same day do not double-count the streak
- SC-003: A 3-day commit gap triggers HUNGRY mood on the next poll
- SC-004: Streak value is never greater than the pet's age in days
- SC-005: longest_streak always reflects the historical peak
