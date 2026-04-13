# GitHub Tamagotchi Constitution

## Core Principles

### I. Repository Health as Pet Health
A pet's state is a direct reflection of its repository's health. Commits feed it, CI success makes it dance, security alerts make it sick, stale PRs make it worried. There is no manual feeding — all state changes derive from real repository activity polled from the GitHub API.

### II. Deterministic Identity
A pet's visual appearance and personality are derived deterministically from the repository's `owner/name` hash. The same repository always produces the same creature, color palette, body type, feature, and personality traits. This makes pets feel like they genuinely belong to their repo.

### III. Gradual, Earned Progression
Pets evolve through six stages (Egg → Baby → Child → Teen → Adult → Elder) by accumulating experience points from real activity. There are no shortcuts. Death is real: 7 days of neglect or 90 days of abandonment ends the pet's life. Resurrection is possible but carries a generation counter — the history is not erased.

### IV. Social Transparency
Contributor behavior is tracked and visible. The blame board names who left PRs open; the heroes board names who closed issues. Leaderboard and blame board participation is opt-out, not opt-in, because transparency is the default. Repo admins can disable these features per-pet.

### V. Badge-First Embeddability
The primary entry point for most users is an SVG badge or animated GIF embedded in a README. The web UI is secondary. Badges must render fast, be cache-friendly, and convey health state at a glance without requiring a login.

### VI. Observable by Default
All internal events are exposed: `/metrics` serves Prometheus counters and gauges, `/api/v1/health` exposes liveness/readiness probes, and alerting fires to Slack/Discord when pets start dying en masse or polls fail. The system must be operable without log-diving.

### VII. Minimal Blast Radius on Failure
GitHub API failures, ComfyUI/OpenRouter timeouts, and image generation errors must never crash the pet loop. Poll errors increment counters, log structured events, and skip the affected pet — they do not propagate. Image generation is a background job queue, decoupled from the web request path.

## Architecture Constraints

- **FastAPI** async web framework, **SQLAlchemy** async ORM, **PostgreSQL** database
- **APScheduler** for the poll loop (configurable interval, default 30 min)
- Image generation via **OpenRouter** (default) or **ComfyUI** (configurable); sprite sheets are 3x2 grids, GIFs composed from extracted frames
- Images stored in **MinIO/S3**-compatible object storage
- **structlog** for structured logging throughout; **Sentry** for error tracking
- **JWT** sessions stored in `HttpOnly` cookies; no server-side session store
- Admin status is determined at runtime by comparing `github_login` against `admin_github_logins` config, not stored permissions alone

## Health Formula

Per poll cycle, `health` is clamped to [0, 100]. Delta is:

```
delta = 0
+ 5   if last CI success
+10   if commit within last 24h
+ min(release_count_30d * 2, 10)   # release frequency bonus, capped at +10
+ min(contributor_count, 8)         # team size bonus, capped at +8
-10   if has_stale_dependencies
 -5   if oldest_pr_age_hours > 48
 -5   if oldest_issue_age_days > 7
- min(critical_alerts * 20 * sec_mult, 40 * sec_mult)
- min(high_alerts    * 10 * sec_mult, 20 * sec_mult)
- min(medium_alerts  *  5 * sec_mult, 10 * sec_mult)
- min(low_alerts     *  2 * sec_mult,  4 * sec_mult)
```

Where `sec_mult = 2` if `dependent_count >= 100`, else `1`.

## Definition of Done

Every change must satisfy ALL before considered complete:
1. Builds clean
2. Tests pass (existing + new for new functionality)
3. Linter passes
4. CI green on the PR
5. Feature branch, not main
6. PR describes what and why
7. No regressions
8. Clean commits (no AI co-author, no branding)

## Governance

Constitution supersedes all other practices. Amendments require a PR with rationale, updated version, and migration plan if behavior changes.

Version: 1.0 | Ratified: 2026-04-13
