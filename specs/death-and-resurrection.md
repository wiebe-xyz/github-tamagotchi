# Feature Specification: Death and Resurrection
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Pets can die from sustained neglect or abandonment, giving the death mechanic real stakes. A 7-day grace period at zero health gives owners time to recover the repo. After death, a memorial page preserves the pet's history. Resurrection resets the pet to EGG stage but increments a generation counter, making lineage visible.

## User Stories

### Dying pet shows warning banner (Priority: P1)
When a pet's health reaches 0, a dying state is visible before actual death.
**Acceptance Scenarios**:
1. Given a pet with health == 0, When the profile page loads, Then a "dying" banner appears
2. Given health == 0 and grace_period_started is set, When the badge is rendered, Then the badge reflects the SICK mood
3. Given health > 0, Then no dying banner appears and grace_period_started is null

### Pet dies after 7-day grace period (Priority: P1)
Sustained zero health for 7 consecutive days triggers death by neglect.
**Acceptance Scenarios**:
1. Given grace_period_started is 8 days ago and health == 0, When check_death_conditions is called, Then it returns (True, "neglect")
2. Given grace_period_started is 5 days ago, When check_death_conditions is called, Then it returns (False, None)
3. Given health recovers above 0 during the grace period, Then grace_period_started is cleared

### Pet dies from abandonment (Priority: P1)
No API activity for 90 days triggers death by abandonment.
**Acceptance Scenarios**:
1. Given last_checked_at is 91 days ago, When check_death_conditions is called, Then it returns (True, "abandonment")
2. Given the repo is polled regularly, Then abandonment never triggers

### Eggs are exempt from death (Priority: P1)
EGG-stage pets cannot die — they haven't hatched yet.
**Acceptance Scenarios**:
1. Given a pet at EGG stage with health == 0, When update_grace_period is called, Then it returns without setting grace_period_started
2. Given a pet at EGG stage inactive for 91 days, When check_death_conditions is called, Then it returns (False, None)

### Memorial page preserved after death (Priority: P2)
Dead pets have a readable memorial page.
**Acceptance Scenarios**:
1. Given is_dead == True, When /pets/{owner}/{repo} is visited, Then the memorial page renders with died_at and cause_of_death
2. Given cause_of_death == "neglect", Then the page shows the appropriate epitaph

### Resurrection resets pet but preserves generation (Priority: P1)
Repo owners can resurrect a dead pet, starting a new generation.
**Acceptance Scenarios**:
1. Given is_dead == True and generation == 1, When resurrection is triggered, Then is_dead = False, stage = EGG, health = 100, experience = 0, generation = 2
2. Given generation == 2, Then the "Phoenix" achievement is unlocked for the pet
3. Given a resurrected pet, Then the previous died_at and cause_of_death are cleared

## Functional Requirements
- **FR-001**: DEATH_GRACE_PERIOD_DAYS = 7
- **FR-002**: ABANDONMENT_THRESHOLD_DAYS = 90
- **FR-003**: update_grace_period() sets grace_period_started when health hits 0 (first time); clears it when health recovers
- **FR-004**: check_death_conditions() checks abandonment first, then neglect
- **FR-005**: Abandonment uses last_checked_at OR last_fed_at OR created_at (whichever is most recent)
- **FR-006**: EGG stage is fully exempt from both death conditions
- **FR-007**: On death: is_dead = True, died_at = now, cause_of_death set to "neglect" or "abandonment"
- **FR-008**: Prometheus counters: `tamagotchi_deaths_total{cause}`, `tamagotchi_resurrections_total`
- **FR-009**: Pets dying (health == 0, not yet dead) tracked in `tamagotchi_pets_dying` gauge
- **FR-010**: Resurrection increments generation and resets to EGG with full health

## Technical Notes
- Key files: `src/github_tamagotchi/services/pet_logic.py` (death functions), `src/github_tamagotchi/models/pet.py` (is_dead, died_at, cause_of_death, grace_period_started, generation fields)
- Death check runs inside poll loop after health update
- `update_grace_period(pet, now)` — call before `check_death_conditions(pet, now)`
- Naive datetime comparison: if `last_activity.tzinfo is None`, compare against naive now
- Alert threshold: `alert_dying_pets_pct = 0.10` (10% of pets dying triggers alert), `alert_death_spike_count = 5`

## Success Criteria
- SC-001: A pet with 0 health for < 7 days stays alive
- SC-002: A pet with 0 health for >= 7 days gets is_dead = True with cause "neglect"
- SC-003: A pet inactive for >= 90 days gets is_dead = True with cause "abandonment"
- SC-004: EGG pets are never marked dead
- SC-005: Resurrected pets have generation >= 2 and stage == EGG
