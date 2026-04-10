"""Prometheus metrics definitions for GitHub Tamagotchi."""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Business metrics — pet state
# ---------------------------------------------------------------------------

pets_total = Gauge(
    "tamagotchi_pets_total",
    "Total pets grouped by stage and mood",
    ["stage", "mood"],
)

pets_active = Gauge(
    "tamagotchi_pets_active",
    "Pets with activity (last_fed_at) in the last 7 days",
)

pets_dying = Gauge(
    "tamagotchi_pets_dying",
    "Pets in the grace period (health == 0, not yet dead)",
)

pets_dead_total = Gauge(
    "tamagotchi_pets_dead_total",
    "Total pets that have died",
)

evolutions_total = Counter(
    "tamagotchi_evolutions_total",
    "Total pet evolutions",
    ["from_stage", "to_stage"],
)

deaths_total = Counter(
    "tamagotchi_deaths_total",
    "Total pet deaths",
    ["cause"],
)

resurrections_total = Counter(
    "tamagotchi_resurrections_total",
    "Total pet resurrections",
)

# ---------------------------------------------------------------------------
# Polling metrics
# ---------------------------------------------------------------------------

poll_duration_seconds = Histogram(
    "tamagotchi_poll_duration_seconds",
    "Time taken to complete a full repository health poll cycle",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

poll_pets_processed = Gauge(
    "tamagotchi_poll_pets_processed",
    "Number of pets processed in the last poll cycle",
)

poll_errors_total = Counter(
    "tamagotchi_poll_errors_total",
    "Total errors encountered during poll cycles",
)

poll_last_success_timestamp = Gauge(
    "tamagotchi_poll_last_success_timestamp",
    "Unix timestamp of the last successful poll cycle completion",
)

# ---------------------------------------------------------------------------
# GitHub API metrics
# ---------------------------------------------------------------------------

github_api_requests_total = Counter(
    "github_api_requests_total",
    "Total GitHub API requests made",
    ["endpoint", "status"],
)

github_api_rate_limit_remaining = Gauge(
    "github_api_rate_limit_remaining",
    "GitHub API rate limit requests remaining",
)

github_api_errors_total = Counter(
    "github_api_errors_total",
    "Total GitHub API errors",
    ["error_type"],
)

# ---------------------------------------------------------------------------
# Webhook metrics
# ---------------------------------------------------------------------------

webhooks_received_total = Counter(
    "tamagotchi_webhooks_received_total",
    "Total webhooks received",
    ["event_type"],
)

webhooks_processed_total = Counter(
    "tamagotchi_webhooks_processed_total",
    "Total webhooks successfully processed",
)

webhooks_failed_total = Counter(
    "tamagotchi_webhooks_failed_total",
    "Total webhooks that failed processing",
)
