# Feature Specification: Monitoring
**Status**: Implemented
**Created**: 2026-04-13

## Overview
The system exposes health probes for container orchestration, a Prometheus metrics endpoint for observability, structured JSON logging via structlog, and an alerting subsystem that fires to Slack and/or Discord when critical conditions are detected.

## User Stories

### Liveness probe confirms process is alive (Priority: P1)
Kubernetes/Nomad liveness checks use /api/v1/health.
**Acceptance Scenarios**:
1. Given the application is running, When GET /api/v1/health is called, Then {"status": "ok"} is returned with 200
2. Given the process is stuck, Then the liveness endpoint would not respond (expected behavior for restart)

### Readiness probe checks critical dependencies (Priority: P1)
Before receiving traffic, all dependencies must be healthy.
**Acceptance Scenarios**:
1. Given database, GitHub API, and scheduler are all healthy, When GET /api/v1/health/ready is called, Then {"status": "healthy"} is returned
2. Given the database is down, Then 503 is returned with {"status": "unhealthy", "checks": {...}}
3. Given GitHub API rate limit < 100, Then the check is "degraded" but not "error"
4. Given the poll_repositories job has no next_run_time, Then the scheduler check returns "error"

### Prometheus metrics are scraped at /metrics (Priority: P1)
The /metrics endpoint exposes all counters and gauges in the Prometheus text format.
**Acceptance Scenarios**:
1. Given the app is running, When GET /metrics is called, Then Prometheus text format is returned
2. Given a pet dies, Then `tamagotchi_deaths_total{cause="neglect"}` increments by 1
3. Given a poll cycle completes, Then `tamagotchi_poll_last_success_timestamp` updates

### Alerting fires when pets are dying en masse (Priority: P2)
Slack and/or Discord webhooks receive alerts when critical thresholds are crossed.
**Acceptance Scenarios**:
1. Given > 10% of pets are in the dying state, When the alert checker runs, Then a notification is sent to configured webhooks
2. Given 5+ pets die in a short window (death spike), Then an alert fires
3. Given poll failures exceed `alert_poll_failure_threshold = 2` consecutive failures, Then an alert fires
4. Given GitHub API rate limit falls below `alert_github_rate_limit_threshold = 100`, Then an alert fires

### Detailed health endpoint available to admins (Priority: P2)
Admins can see full system status including uptime and activity stats.
**Acceptance Scenarios**:
1. Given an admin calls GET /api/v1/health/detailed, Then response includes version, uptime, checks, and stats
2. Given a non-admin calls it, Then 403 is returned
3. Stats include: total_pets, active_pets, dead_pets, polls_last_hour, webhooks_last_hour, errors_last_hour

## Functional Requirements
- **FR-001**: GET /api/v1/health — liveness probe, always returns 200 if process is alive
- **FR-002**: GET /api/v1/health/ready — readiness probe; checks database, GitHub API, scheduler; returns 503 if any check is "error"
- **FR-003**: GET /api/v1/health/detailed — admin-only; full system status with uptime and activity stats
- **FR-004**: GET /metrics — Prometheus text format (prometheus_client library)
- **FR-005**: HTTP metrics: `http_requests_total{method,endpoint,status}`, `http_request_duration_seconds{endpoint}`
- **FR-006**: Pet state gauges: `tamagotchi_pets_total{stage,mood}`, `tamagotchi_pets_active`, `tamagotchi_pets_dying`, `tamagotchi_pets_dead_total`
- **FR-007**: Event counters: `tamagotchi_evolutions_total{from_stage,to_stage}`, `tamagotchi_deaths_total{cause}`, `tamagotchi_resurrections_total`
- **FR-008**: Poll metrics: `tamagotchi_poll_duration_seconds` (histogram), `tamagotchi_poll_pets_processed`, `tamagotchi_poll_errors_total`, `tamagotchi_poll_last_success_timestamp`
- **FR-009**: GitHub API metrics: `github_api_requests_total{endpoint,status}`, `github_api_rate_limit_remaining`, `github_api_errors_total{error_type}`
- **FR-010**: Webhook metrics: `tamagotchi_webhooks_received_total{event_type}`, `tamagotchi_webhooks_processed_total`, `tamagotchi_webhooks_failed_total`
- **FR-011**: Alerting thresholds (all configurable): poll_failure_threshold=2, error_rate_threshold=0.05, rate_limit_threshold=100, db_slow_query_ms=500, dying_pets_pct=0.10, death_spike_count=5, check_interval_minutes=5
- **FR-012**: Alert targets: Slack webhook (alert_slack_webhook), Discord webhook (alert_discord_webhook)
- **FR-013**: structlog used throughout for structured JSON log output; Sentry integration via sentry_dsn config

## Technical Notes
- Key files: `src/github_tamagotchi/metrics.py` (Prometheus definitions), `src/github_tamagotchi/api/health.py` (health endpoints), `src/github_tamagotchi/services/alerting.py` (AlertChecker), `src/github_tamagotchi/main.py` (/metrics route)
- Prometheus metrics use `prometheus_client` library; `/metrics` endpoint serves `generate_latest()` with `CONTENT_TYPE_LATEST`
- Database readiness uses `SELECT 1` with latency threshold of 1000ms for "degraded"
- Scheduler check inspects `scheduler.get_job("poll_repositories")` next_run_time
- Uptime tracked via `get_uptime_seconds()` from core scheduler module
- `JobRun` model records every poll cycle: job_name, started_at, errors_count

## Success Criteria
- SC-001: Liveness probe returns 200 within 100ms under normal operation
- SC-002: Readiness probe returns 503 within 5 seconds of database going down
- SC-003: All Prometheus metrics are non-zero after at least one poll cycle
- SC-004: Slack/Discord alert is sent within one check_interval_minutes of a death spike
- SC-005: Detailed health endpoint shows accurate activity stats for the last hour
