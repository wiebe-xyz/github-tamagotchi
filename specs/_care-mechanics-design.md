# Care mechanics design contract (issue #259)

Working design doc for implementing this feature across parallel subagents.
Delete or fold into `specs/pet-lifecycle.md` / `specs/pet-personalization.md`
once the feature is integrated — this file is scaffolding, not the final spec.

## Already done (do not redo)
- Migration `alembic/versions/032_add_care_mechanics.py`: adds `pets.mess_level`
  (Integer, default 0), `pets.last_cleaned_at` (DateTime, nullable),
  `pets.last_played_at` (DateTime, nullable).
- `models/pet.py`: `Pet.mess_level`, `Pet.last_cleaned_at`, `Pet.last_played_at`
  columns added. `PetMood` gained `SLEEPING = "sleeping"` and `DIRTY = "dirty"`.
- Hunger-from-neglect reuses the existing `pets.last_fed_at` column — no new
  column for it.

## Scope boundary (important)
Health, XP, and evolution stay driven ONLY by real repo activity via
`update_pet_from_repo` — none of this touches those. This is a mood/display
layer only, exactly like the existing weight/feeding mechanic in
`services/pet_feeding.py` (read that file for the established pattern:
small dataclass result types, mutate-pet-in-place functions, `caller commits`).

## Four independent modules — one per subagent, each a NEW file only

Each subagent implements exactly one file plus its own test file. Do not
touch `models/pet.py`, `mcp/server.py`, `services/pet_logic.py`, or any
other subagent's file — those are integrated in a later, separate pass.
Follow this repo's existing code style (see `services/pet_feeding.py` for
tone/structure — module docstring explaining the mechanic, constants at
top, small pure-ish functions that mutate a passed-in `Pet` and let the
caller commit).

### 1. `src/github_tamagotchi/services/pet_care/mess.py`
```python
MESS_PER_FEED = 1
MESS_DIRTY_THRESHOLD = 3

def add_mess(pet: Pet) -> None: ...          # pet.mess_level += MESS_PER_FEED
def clean_pet(pet: Pet, now: datetime) -> int: ...  # reset to 0, set last_cleaned_at, return level that was cleared
def is_dirty(pet: Pet) -> bool: ...          # pet.mess_level >= MESS_DIRTY_THRESHOLD
def mess_label(pet: Pet) -> str: ...         # "clean" / "a little messy" / "filthy" for responses/ASCII art
```

### 2. `src/github_tamagotchi/services/pet_care/boredom.py`
Boredom decay rate scales with the pet's `activity` personality trait
(higher activity = bored faster = shorter threshold). Import
`PetPersonality` from `services.pet_logic` for the type hint only.
```python
BOREDOM_MAX_HOURS = 96   # activity=0.0 (lazy) — slowest to get bored
BOREDOM_MIN_HOURS = 12   # activity=1.0 (active) — fastest to get bored

def boredom_threshold_hours(activity: float) -> float: ...  # linear interpolation, clamp activity to [0,1]
def is_bored(pet: Pet, activity: float, now: datetime) -> bool: ...
```
`is_bored`: reference point is `pet.last_played_at or pet.created_at` (never
played yet = grace period from hatching, not instant boredom). Bored if
hours since reference > `boredom_threshold_hours(activity)`.

### 3. `src/github_tamagotchi/services/pet_care/neglect_hunger.py`
Distinct from the EXISTING repo-inactivity hunger check in
`services/pet_logic.py` (`HUNGRY_THRESHOLD_DAYS`, based on `last_commit_at`)
— that one stays as-is. This is a second, independent hunger signal based on
whether the pet itself has been fed, scaling with the `appetite` trait
(higher appetite = "Hungry" trait = gets hungry faster = shorter threshold).
```python
NEGLECT_HUNGER_MAX_HOURS = 120  # appetite=0.0 (light eater) — slowest to get hungry
NEGLECT_HUNGER_MIN_HOURS = 24   # appetite=1.0 (hungry trait) — fastest to get hungry

def neglect_hunger_threshold_hours(appetite: float) -> float: ...  # linear interpolation, clamp to [0,1]
def is_neglected_hungry(pet: Pet, appetite: float, now: datetime) -> bool: ...
```
`is_neglected_hungry`: reference point is `pet.last_fed_at or pet.created_at`.

### 4. `src/github_tamagotchi/services/pet_care/sleep.py`
Pure time-of-day function, no persisted state, no personality input.
```python
SLEEP_START_HOUR_UTC = 22  # inclusive
SLEEP_END_HOUR_UTC = 7     # exclusive

def is_asleep(now: datetime) -> bool: ...  # UTC hour in [22:00, 07:00) — wraps midnight
```

## Tests
One test file per module under `tests/services/` (e.g. `test_pet_mess.py`,
`test_pet_boredom.py`, `test_pet_neglect_hunger.py`, `test_pet_sleep.py`),
following the style of `tests/services/test_pet_feeding.py`. Cover
threshold boundaries (just under / at / just over), the trait-scaling
interpolation at 0.0/0.5/1.0, and the "never interacted yet" grace-period
case for boredom/neglect-hunger. Sleep needs the midnight-wrap case tested
explicitly (e.g. 23:30 UTC and 03:00 UTC both asleep, 12:00 UTC awake).

## Integration pass (separate agent, after all four above land)

1. **`services/pet_logic.py`**: add a new `calculate_mood_with_care(health,
   pet, personality, now) -> PetMood` that calls the existing
   `calculate_mood(health, pet.health)` for the base mood, then applies, in
   order (first match wins, and SICK is never overridden):
   - if base mood is `SICK` → return `SICK` (unchanged, a sick pet doesn't
     sleep peacefully or notice mess)
   - `sleep.is_asleep(now)` → `SLEEPING`
   - `mess.is_dirty(pet)` → `DIRTY`
   - `neglect_hunger.is_neglected_hungry(pet, personality.appetite, now)` →
     `HUNGRY`
   - `boredom.is_bored(pet, personality.activity, now)` → `LONELY`
   - else → the base mood unchanged
   Do NOT modify the existing `calculate_mood` — it's covered by existing
   tests and other priorities (security/PR-age/issue-age/solo-maintainer/
   dancing) stay exactly as they are.

2. **`mcp/server.py`**:
   - `update_pet_from_repo`: call `calculate_mood_with_care` instead of
     `calculate_mood` (needs `pet`, `personality`, `now` — personality is
     already fetched via `_get_pet_personality` a few lines below current
     mood calc, so fetch it earlier in this function).
   - `feed_pet`: call `mess.add_mess(pet)` after `apply_feed`. If
     `sleep.is_asleep(now)`, skip the whole feed effect and return early
     with an informative "sleeping" message and no mutation (don't add
     mess, don't call apply_feed, don't update last_fed_at).
   - `play_with_pet`: if `sleep.is_asleep(now)`, skip entirely (no mood
     nudge, no `last_played_at` update) and return an informative
     "sleeping" message + ascii art. If awake, set
     `pet.last_played_at = datetime.now(UTC)` unconditionally (even when
     the existing happiness-nudge is on cooldown — a visit should count
     against boredom even if the mood nudge itself is throttled).
   - New tool `clean_pet(repo_owner, repo_name)`: always allowed, even
     while asleep. Calls `mess.clean_pet(pet, now)`. If `pet.mood ==
     PetMood.DIRTY.value` after cleaning, set `pet.mood =
     PetMood.CONTENT.value` directly (same direct-mutation pattern as
     `nudge_mood_happier` — no GitHub call needed). Commit. Return the
     amount of mess cleared + updated pet status + ascii art (mirror
     `play_with_pet`'s response shape).
   - `check_pet_status`: include `mess_level`/dirty label and `is_asleep`
     in the response, using the new modules (read-only, no mutation).
   - Register `clean_pet` in the MCP tool list.
   - Update the module-level `INSTRUCTIONS` string and this repo's
     `README.md` "MCP Integration" section (tool list + one-line
     description) to mention `clean_pet`.

3. **`schemas/pets.py`**: extend `PetResponse` with the new fields the API
   should expose (mess/dirty, is_asleep) if that schema mirrors MCP
   responses — check current fields first, follow existing convention.

4. **Spec doc**: write `specs/pet-care-mechanics.md` (spec-kit style, match
   the structure of `specs/pet-lifecycle.md`) documenting what was
   actually built — thresholds, priority order, the "no penalty while
   asleep" behavior — then delete this `_care-mechanics-design.md` file (it
   was scaffolding for implementation, not a permanent spec) and add a row
   for the new spec to the table in `README.md`'s "Spec-Driven Development"
   section.

5. Run full suite: `uv run pytest`, `uv run ruff check .`, `uv run mypy .`.
   Fix anything broken. The repo enforces a 75% coverage gate — make sure
   new code is covered by the tests from steps 1-4 above plus whatever
   integration-level test is needed for `update_pet_from_repo` /
   `clean_pet` (check `tests/services/test_mcp_server.py` for the existing
   pattern of testing MCP tools).

6. Commit (no AI co-author, no AI branding — plain conventional commit
   message), push the `issue-259/care-mechanics` branch, open a PR against
   `main` with a body describing what/why, and watch CI
   (`gh pr checks --watch`). Fix any red CI. Do NOT merge — leave it for
   human review.
