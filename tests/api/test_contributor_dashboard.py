"""Tests for the contributor dashboard page at /dashboard/{username}."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.services.github import ContributorStats
from tests.conftest import test_session_factory


def _create_user(user_id: int = 100, github_login: str = "contributor") -> str:
    async def _setup() -> str:
        async with test_session_factory() as session:
            user = User(
                id=user_id,
                github_id=user_id * 1000,
                github_login=github_login,
                github_avatar_url=f"https://avatars.example.com/{github_login}",
            )
            session.add(user)
            await session.commit()
        return _create_jwt(user_id=user_id)

    return asyncio.run(_setup())


def _create_pet(
    user_id: int | None = None,
    repo_owner: str = "teamorg",
    repo_name: str = "repo",
    name: str = "Gotchi",
    stage: str = PetStage.ADULT.value,
    health: int = 80,
    is_dead: bool = False,
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                user_id=user_id,
                stage=stage,
                mood=PetMood.HAPPY.value,
                health=health,
                is_dead=is_dead,
                died_at=datetime.now(UTC) if is_dead else None,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


def _no_contribution_stats() -> ContributorStats:
    return ContributorStats(
        commits_30d=0,
        last_commit_at=None,
        is_top_contributor=False,
        has_failed_ci=False,
        days_since_last_commit=None,
    )


def _active_stats(commits_30d: int = 5, is_top: bool = False) -> ContributorStats:
    return ContributorStats(
        commits_30d=commits_30d,
        last_commit_at=datetime.now(UTC) - timedelta(days=3),
        is_top_contributor=is_top,
        has_failed_ci=False,
        days_since_last_commit=3,
    )


def _absent_stats(days: int = 45) -> ContributorStats:
    return ContributorStats(
        commits_30d=0,
        last_commit_at=datetime.now(UTC) - timedelta(days=days),
        is_top_contributor=False,
        has_failed_ci=False,
        days_since_last_commit=days,
    )


class TestContributorDashboardPublic:
    def test_page_returns_200_for_any_username(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/someuser")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_shows_username_in_header(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/alice")
        assert "alice" in response.text

    def test_no_pets_shows_empty_state(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/ghost")
        assert response.status_code == 200
        # No pets owned, no team pets
        assert "ghost" in response.text


class TestContributorDashboardOwnedPets:
    def test_shows_owned_pet_in_your_pets_section(self, client: TestClient) -> None:
        _create_pet(repo_owner="repoowner", repo_name="myrepo", name="Fluffy")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/repoowner")
        assert "Fluffy" in response.text
        assert "repoowner/myrepo" in response.text

    def test_shows_health_bar_for_owned_pet(self, client: TestClient) -> None:
        _create_pet(repo_owner="healthowner", repo_name="repo", name="Barney", health=75)
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/healthowner")
        assert "75%" in response.text

    def test_shows_view_profile_link_for_owned_pet(self, client: TestClient) -> None:
        _create_pet(repo_owner="linkowner2", repo_name="linkrepo2", name="Link")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/linkowner2")
        assert "/pet/linkowner2/linkrepo2" in response.text


class TestContributorDashboardTeamPets:
    def test_shows_team_pet_when_user_is_contributor(self, client: TestClient) -> None:
        _create_pet(repo_owner="teamorg2", repo_name="api", name="Chippy")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(commits_30d=5),
        ):
            response = client.get("/dashboard/devuser")
        assert "Chippy" in response.text
        assert "teamorg2/api" in response.text

    def test_shows_favorite_standing(self, client: TestClient) -> None:
        _create_pet(repo_owner="corp3", repo_name="main", name="Star")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(commits_30d=10, is_top=True),
        ):
            response = client.get("/dashboard/topdev")
        assert "Favorite" in response.text

    def test_shows_good_standing(self, client: TestClient) -> None:
        _create_pet(repo_owner="corp4", repo_name="frontend", name="Buddy")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(commits_30d=3, is_top=False),
        ):
            response = client.get("/dashboard/activedev")
        assert "Good" in response.text

    def test_shows_absent_standing(self, client: TestClient) -> None:
        _create_pet(repo_owner="corp5", repo_name="legacy", name="Rex")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_absent_stats(days=45),
        ):
            response = client.get("/dashboard/idledev")
        assert "Absent" in response.text

    def test_excludes_non_contributor_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="strangerorg", repo_name="repo", name="Stranger")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/notacontributor")
        # Pet should not appear in team pets since user never contributed
        assert "Stranger" not in response.text

    def test_excludes_dead_pets_from_team_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="deadorg", repo_name="deadrepo", name="Ghost", is_dead=True)
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(),
        ) as mock_stats:
            client.get("/dashboard/anydev")
        # Dead pets in OTHER users' repos should not appear in team pets
        assert mock_stats.call_count == 0

    def test_shows_redemption_path_for_absent_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="corp6", repo_name="infra", name="Spot")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_absent_stats(days=34),
        ):
            response = client.get("/dashboard/idledev2")
        assert "Redemption Path" in response.text
        assert "34 days ago" in response.text

    def test_shows_link_to_pet_profile_in_team(self, client: TestClient) -> None:
        _create_pet(repo_owner="corp7", repo_name="backend", name="Zippy")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(),
        ):
            response = client.get("/dashboard/devlink")
        assert "/pet/corp7/backend" in response.text


class TestContributorDashboardStats:
    def test_shows_total_repos_count(self, client: TestClient) -> None:
        _create_pet(repo_owner="statowner", repo_name="r1", name="Pet1")
        _create_pet(repo_owner="statteam", repo_name="r2", name="Pet2")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_active_stats(commits_30d=2),
        ):
            response = client.get("/dashboard/statowner")
        assert response.status_code == 200

    def test_authenticated_user_sees_nav_links(self, client: TestClient) -> None:
        token = _create_user(user_id=200, github_login="navuser")
        with patch(
            "github_tamagotchi.main.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=_no_contribution_stats(),
        ):
            response = client.get("/dashboard/navuser", cookies={"session_token": token})
        assert "My Pets" in response.text
        assert "Register" in response.text
