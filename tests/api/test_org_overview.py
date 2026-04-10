"""Tests for the org-wide pet overview page at /org/{org_name}."""

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from tests.conftest import test_session_factory


def _create_pet(
    repo_owner: str = "bigcorp",
    repo_name: str = "api",
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
                stage=stage,
                mood=PetMood.HAPPY.value,
                health=health,
                is_dead=is_dead,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


class TestOrgOverviewBasic:
    def test_page_returns_200(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/someorg")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_shows_org_name_in_header(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/bigcorp")
        assert "bigcorp" in response.text

    def test_empty_org_shows_empty_state(self, client: TestClient) -> None:
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/nopetshere")
        assert response.status_code == 200
        assert "No pets registered" in response.text


class TestOrgOverviewPets:
    def test_shows_org_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="acme", repo_name="backend", name="Atlas")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/acme")
        assert "Atlas" in response.text
        assert "acme/backend" in response.text

    def test_does_not_show_other_org_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="otheracme", repo_name="repo", name="Stranger")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/acme2")
        assert "Stranger" not in response.text

    def test_case_insensitive_org_match(self, client: TestClient) -> None:
        _create_pet(repo_owner="MyOrg", repo_name="project", name="Cased")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/myorg")
        assert "Cased" in response.text

    def test_shows_pet_profile_link(self, client: TestClient) -> None:
        _create_pet(repo_owner="linkorg", repo_name="proj", name="Linky")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/linkorg")
        assert "/pet/linkorg/proj" in response.text

    def test_shows_health_bar(self, client: TestClient) -> None:
        _create_pet(repo_owner="healthorg", repo_name="svc", name="Barney", health=60)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/healthorg")
        assert "60" in response.text


class TestOrgOverviewHealthStats:
    def test_shows_aggregate_pet_count(self, client: TestClient) -> None:
        _create_pet(repo_owner="statsorg", repo_name="r1", name="P1", health=90)
        _create_pet(repo_owner="statsorg", repo_name="r2", name="P2", health=50)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/statsorg")
        assert "2 pets" in response.text

    def test_shows_healthy_hungry_sick_counts(self, client: TestClient) -> None:
        _create_pet(repo_owner="countorg", repo_name="r1", name="H", health=80)
        _create_pet(repo_owner="countorg", repo_name="r2", name="N", health=50)
        _create_pet(repo_owner="countorg", repo_name="r3", name="S", health=10)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/countorg")
        assert "Healthy" in response.text
        assert "Hungry" in response.text
        assert "Sick" in response.text


class TestOrgOverviewCaretaker:
    def test_shows_top_caretaker_when_available(self, client: TestClient) -> None:
        _create_pet(repo_owner="caretakerorg", repo_name="repo", name="Fluffy")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value="alice",
        ):
            response = client.get("/org/caretakerorg")
        assert "@alice" in response.text

    def test_shows_nobody_when_no_caretaker(self, client: TestClient) -> None:
        _create_pet(repo_owner="nocaretakerorg", repo_name="repo", name="Lonely")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/nocaretakerorg")
        assert "Nobody" in response.text

    def test_caretaker_links_to_dashboard(self, client: TestClient) -> None:
        _create_pet(repo_owner="linkcaretakerorg", repo_name="repo", name="Dino")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value="bob",
        ):
            response = client.get("/org/linkcaretakerorg")
        assert "/dashboard/bob" in response.text


class TestOrgOverviewLeaderboard:
    def test_shows_org_leaderboard_section(self, client: TestClient) -> None:
        _create_pet(repo_owner="lbdorg", repo_name="r1", name="L1")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value="topdev",
        ):
            response = client.get("/org/lbdorg")
        assert "Org Leaderboard" in response.text
        assert "@topdev" in response.text

    def test_leaderboard_not_shown_when_no_caretakers(self, client: TestClient) -> None:
        _create_pet(repo_owner="nolbdorg", repo_name="r1", name="N1")
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/nolbdorg")
        assert "Org Leaderboard" not in response.text


class TestOrgOverviewNeglected:
    def test_shows_neglected_section_for_sick_pet(self, client: TestClient) -> None:
        _create_pet(repo_owner="neglectorg", repo_name="legacy", name="Sick", health=15)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/neglectorg")
        assert "Neglected Repos" in response.text
        assert "neglectorg/legacy" in response.text

    def test_shows_neglected_section_for_dead_pet(self, client: TestClient) -> None:
        _create_pet(repo_owner="deadorg", repo_name="rip", name="Ghost", is_dead=True)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/deadorg")
        assert "Neglected Repos" in response.text
        assert "deadorg/rip" in response.text

    def test_neglected_not_shown_for_healthy_pets(self, client: TestClient) -> None:
        _create_pet(repo_owner="healthyorg", repo_name="good", name="Fit", health=90)
        with patch(
            "github_tamagotchi.main.GitHubService.get_top_contributor",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get("/org/healthyorg")
        assert "Neglected Repos" not in response.text
