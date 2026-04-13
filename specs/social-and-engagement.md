# Feature Specification: Social and Engagement
**Status**: Implemented
**Created**: 2026-04-13

## Overview
Beyond the single-pet view, the platform has social features to encourage sharing and comparison: a multi-category leaderboard, 18 achievements, Open Graph meta tags for rich link previews, embeddable SVG badges and animated GIFs, and a comment system on pet profiles.

## User Stories

### Leaderboard ranks pets across multiple categories (Priority: P1)
The leaderboard provides competitive context across all public pets.
**Acceptance Scenarios**:
1. Given multiple pets are registered, When /api/v1/leaderboard is fetched, Then it returns categories with ranked entries
2. Given a pet has leaderboard_opt_out == True, Then it is excluded from all categories
3. Given the leaderboard is cached, Then repeated requests within the cache window return the same cached_at timestamp

### Pet earns achievements automatically (Priority: P2)
Achievements unlock when conditions are met on poll or on specific actions.
**Acceptance Scenarios**:
1. Given commit_streak >= 7, Then the "week_warrior" achievement is unlocked
2. Given longest_streak >= 30, Then "month_legend" is unlocked
3. Given generation >= 2 (resurrected), Then "phoenix" is unlocked
4. Given star_count >= 100, Then "stars_100" cosmetic achievement is unlocked
5. Given comment_count >= 10, Then "social_butterfly" is unlocked
6. Achievements do not unlock more than once per pet (UniqueConstraint)

### Pet profile has rich social previews (Priority: P2)
Sharing a pet's URL produces a rich embed in Slack, Twitter, Discord, etc.
**Acceptance Scenarios**:
1. Given a user shares `/pets/octocat/hello-world`, Then the page has og:title, og:description, og:image, og:type="website" meta tags
2. Given the pet has a generated image, Then og:image points to the pet's image URL
3. Given Twitter card tags are present, Then twitter:card="summary_large_image" is set

### Badges are embeddable in README files (Priority: P1)
The primary distribution mechanism is a Markdown badge in the README.
**Acceptance Scenarios**:
1. Given a pet exists, When /api/v1/pets/{owner}/{repo}/badge is fetched, Then an SVG is returned with Cache-Control headers
2. Given the badge style is "minimal", Then a minimal SVG layout is used
3. Given the pet is SICK, Then the badge shows red health bar and sick mood emoji
4. Given an animated GIF is requested, Then /api/v1/pets/{owner}/{repo}/gif returns the animated GIF

### Users can comment on pet profiles (Priority: P3)
Visitors can leave comments on a pet's profile page.
**Acceptance Scenarios**:
1. Given an authenticated user, When they POST to /api/v1/pets/{owner}/{repo}/comments, Then a comment is stored
2. Given comments exist, When the profile page loads, Then comments are displayed in order
3. Given a comment body > 500 chars, Then the API returns 422

## Functional Requirements
- **FR-001**: Leaderboard categories include: health, experience, streak, and star-based rankings
- **FR-002**: LeaderboardEntry: rank, pet_name, repo_owner, repo_name, stage, value
- **FR-003**: `leaderboard_opt_out` field on Pet excludes pet from all categories
- **FR-004**: 18 achievements defined in `ACHIEVEMENTS` dict: streak-based (first_commit, week_warrior, month_legend), stage-based (hatchling, all_grown_up, elder_god), health-based (survivor, centurion), social (social_butterfly), resurrection (phoenix), star milestones (stars_10/100/500/1000/10000), fork milestones (forks_1/10/100)
- **FR-005**: Cosmetic achievements (stars_*, forks_*) flagged with `"cosmetic": True`
- **FR-006**: PetAchievement table: pet_id, achievement_id, unlocked_at; UniqueConstraint prevents duplicates
- **FR-007**: OG tags: og:title="{name} — the {stage}", og:description includes health/mood, og:image points to generated image
- **FR-008**: Twitter card: twitter:card="summary_large_image", twitter:title, twitter:description, twitter:image
- **FR-009**: Badge styles: playful (default with animation), minimal (compact), maintained (clean/professional)
- **FR-010**: Badge served with `Cache-Control: no-cache` to ensure freshness on embed
- **FR-011**: GIF endpoint returns animated GIF built from stored sprite frames for the current stage and mood
- **FR-012**: Comments: body 1-500 chars, author_name stored, created_at timestamp

## Technical Notes
- Key files: `src/github_tamagotchi/services/achievements.py`, `src/github_tamagotchi/services/badge.py`, `src/github_tamagotchi/api/routes.py`, `src/github_tamagotchi/models/achievement.py`, `src/github_tamagotchi/models/comment.py`
- `check_and_unlock_achievements(pet, session)` is called on every poll cycle
- `ACHIEVEMENT_ORDER` list defines display order in the UI
- Badge SVG uses inline `<style>` with CSS keyframe animations per mood
- `MOOD_ANIMATION` maps each mood to an animation name and timing string
- Badge layout constants: width=160px, sprite section 56x56px at x=4,y=9, text starts at x=66

## Success Criteria
- SC-001: Achievements unlock within one poll cycle of conditions being met
- SC-002: Badge SVG renders correctly in GitHub READMEs and returns in <200ms
- SC-003: OG meta tags produce a rich preview when the URL is pasted in Slack
- SC-004: Leaderboard updates reflect current pet state after each poll cycle
