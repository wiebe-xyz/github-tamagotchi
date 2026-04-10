"""Tests for the pet insights page."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import RepoInsights, WeeklyCommits
from tests.conftest import test_session_factory


def _create_pet(
    repo_owner: str = "insightowner",
    repo_name: str = "insightrepo",
    name: str = "Insighty",
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                stage=PetStage.BABY.value,
                mood=PetMood.HAPPY.value,
                health=80,
                experience=100,
                created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


def _make_insights(
    total_commits: int = 20,
    avg_pr_merge_hours: float | None = 12.0,
    avg_issue_response_hours: float | None = 5.0,
    ci_pass_rate: float | None = 0.9,
    ci_runs_checked: int = 10,
    contributor_count: int = 3,
) -> RepoInsights:
    weeks = [
        WeeklyCommits(week_label="Mar 10", count=4),
        WeeklyCommits(week_label="Mar 17", count=6),
        WeeklyCommits(week_label="Mar 24", count=5),
        WeeklyCommits(week_label="Mar 31", count=5),
    ]
    return RepoInsights(
        weekly_commits=weeks,
        total_commits_30d=total_commits,
        avg_pr_merge_hours=avg_pr_merge_hours,
        open_prs_count=2,
        avg_issue_response_hours=avg_issue_response_hours,
        ci_pass_rate=ci_pass_rate,
        ci_runs_checked=ci_runs_checked,
        contributor_count_90d=contributor_count,
    )


class TestPetInsightsPage:
    """Tests for /pet/{owner}/{repo}/insights page."""

    def test_returns_html(self, client: TestClient) -> None:
        """Insights page should return HTML."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_repo_name(self, client: TestClient) -> None:
        """Insights page should show owner/repo."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "insightowner" in response.text
        assert "insightrepo" in response.text

    def test_contains_pet_name(self, client: TestClient) -> None:
        """Insights page should show pet name."""
        _create_pet(name="Insighty")
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Insighty" in response.text

    def test_contains_commit_frequency_section(self, client: TestClient) -> None:
        """Insights page should show commit frequency section."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(total_commits=20),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Commit Frequency" in response.text
        assert "20 total commits" in response.text

    def test_contains_ci_health_section(self, client: TestClient) -> None:
        """Insights page should show CI health section."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(ci_pass_rate=0.9, ci_runs_checked=10),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "CI Health" in response.text
        assert "90%" in response.text

    def test_contains_contributor_section(self, client: TestClient) -> None:
        """Insights page should show contributor activity."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(contributor_count=4),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Contributor Activity" in response.text
        assert "4" in response.text

    def test_shows_unavailable_when_api_fails(self, client: TestClient) -> None:
        """Insights page should show unavailable notice when API call fails."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert response.status_code == 200
        assert "Could not load insights" in response.text

    def test_not_found_returns_404(self, client: TestClient) -> None:
        """Non-existent pet should return 404."""
        response = client.get("/pet/nobody/nonexistent/insights")
        assert response.status_code == 404

    def test_shows_pet_correlations(self, client: TestClient) -> None:
        """Insights page should show pet correlation messages."""
        _create_pet(name="Insighty")
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(total_commits=25),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Insighty" in response.text
        assert "commits" in response.text

    def test_shows_no_commits_correlation(self, client: TestClient) -> None:
        """Insights page should flag no commits with a correlation message."""
        _create_pet(name="Insighty")
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(total_commits=0),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "starving" in response.text

    def test_contains_back_link(self, client: TestClient) -> None:
        """Insights page should have a link back to the pet profile."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "/pet/insightowner/insightrepo" in response.text

    def test_shows_bus_factor_warning(self, client: TestClient) -> None:
        """Should show bus factor warning when only 1 contributor."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(contributor_count=1),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Bus factor" in response.text

    def test_cache_control_header(self, client: TestClient) -> None:
        """Insights page should include cache control header."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "Cache-Control" in response.headers

    def test_no_ci_data_shows_graceful_message(self, client: TestClient) -> None:
        """When no CI data is available, should show a graceful message."""
        _create_pet()
        with patch(
            "github_tamagotchi.main.GitHubService.get_repo_insights",
            new_callable=AsyncMock,
            return_value=_make_insights(ci_pass_rate=None, ci_runs_checked=0),
        ):
            response = client.get("/pet/insightowner/insightrepo/insights")
        assert "No CI data found" in response.text
