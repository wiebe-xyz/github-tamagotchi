"""Tests for the /metrics Prometheus endpoint."""

from fastapi.testclient import TestClient


class TestMetricsEndpoint:
    """Tests for GET /metrics on the production app."""

    def test_metrics_returns_200(self, client: TestClient) -> None:
        """The /metrics endpoint should return HTTP 200."""
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type(self, client: TestClient) -> None:
        """Response must carry a Prometheus-compatible content-type."""
        response = client.get("/metrics")
        ct = response.headers.get("content-type", "")
        assert "text/plain" in ct

    def test_metrics_contains_poll_metrics(self, client: TestClient) -> None:
        """Polling metric names should be exported."""
        response = client.get("/metrics")
        body = response.text
        assert "tamagotchi_poll_errors_total" in body
        assert "tamagotchi_poll_duration_seconds" in body
        assert "tamagotchi_poll_last_success_timestamp" in body

    def test_metrics_contains_business_metrics(self, client: TestClient) -> None:
        """Business metric names should be exported."""
        response = client.get("/metrics")
        body = response.text
        assert "tamagotchi_evolutions_total" in body
        assert "tamagotchi_deaths_total" in body
        assert "tamagotchi_resurrections_total" in body
        assert "tamagotchi_pets_dying" in body
        assert "tamagotchi_pets_dead_total" in body
        assert "tamagotchi_pets_active" in body

    def test_metrics_contains_github_api_metrics(self, client: TestClient) -> None:
        """GitHub API metric names should be exported."""
        response = client.get("/metrics")
        body = response.text
        assert "github_api_requests_total" in body
        assert "github_api_rate_limit_remaining" in body
        assert "github_api_errors_total" in body

    def test_metrics_contains_webhook_metrics(self, client: TestClient) -> None:
        """Webhook metric names should be exported."""
        response = client.get("/metrics")
        body = response.text
        assert "tamagotchi_webhooks_received_total" in body
        assert "tamagotchi_webhooks_processed_total" in body
        assert "tamagotchi_webhooks_failed_total" in body

    def test_metrics_format_is_valid_prometheus_text(self, client: TestClient) -> None:
        """Output should be valid Prometheus text: lines start with # or a metric name."""
        response = client.get("/metrics")
        assert response.status_code == 200
        for line in response.text.splitlines():
            stripped = line.strip()
            if stripped:
                assert (
                    stripped.startswith("#")
                    or stripped[0].isalpha()
                    or stripped[0] == "_"
                ), f"Unexpected line in metrics output: {stripped!r}"

    def test_http_request_metrics_registered(self, client: TestClient) -> None:
        """http_requests_total counter should appear in metrics output."""
        response = client.get("/metrics")
        body = response.text
        assert "http_requests_total" in body

    def test_http_request_duration_histogram_registered(self, client: TestClient) -> None:
        """HTTP duration histogram should appear in metrics output."""
        response = client.get("/metrics")
        body = response.text
        assert "http_request_duration_seconds" in body
