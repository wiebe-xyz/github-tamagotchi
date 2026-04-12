"""Tests for the leaderboard API endpoint and HTML page."""

import asyncio

from fastapi.testclient import TestClient
from httpx import AsyncClient

from github_tamagotchi.crud.pet import _leaderboard_cache
from github_tamagotchi.models.pet import Pet
from tests.conftest import test_session_factory


class TestLeaderboardEndpoint:
    """Tests for GET /api/v1/leaderboard."""

    async def test_leaderboard_returns_200(self, async_client: AsyncClient) -> None:
        """Leaderboard endpoint should return 200 OK."""
        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        assert response.status_code == 200

    async def test_leaderboard_returns_two_categories(self, async_client: AsyncClient) -> None:
        """Leaderboard should return both required categories."""
        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()
        assert "categories" in data
        ids = [c["id"] for c in data["categories"]]
        assert "most_experienced" in ids
        assert "longest_streak" in ids

    async def test_leaderboard_empty_when_no_pets(self, async_client: AsyncClient) -> None:
        """Each category should have empty entries when there are no pets."""
        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()
        for cat in data["categories"]:
            assert cat["entries"] == []

    async def test_leaderboard_ranks_pets_by_experience(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Most Experienced category should rank pets by XP descending."""
        from tests.conftest import test_session_factory

        _leaderboard_cache.clear()
        async with test_session_factory() as session:
            # Create pets with different XP
            high_xp = Pet(repo_owner="org", repo_name="high", name="HighXP", experience=5000)
            low_xp = Pet(repo_owner="org", repo_name="low", name="LowXP", experience=100)
            session.add_all([low_xp, high_xp])
            await session.commit()

        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()

        most_exp = next(c for c in data["categories"] if c["id"] == "most_experienced")
        assert len(most_exp["entries"]) == 2
        assert most_exp["entries"][0]["pet_name"] == "HighXP"
        assert most_exp["entries"][0]["rank"] == 1
        assert most_exp["entries"][1]["pet_name"] == "LowXP"
        assert most_exp["entries"][1]["rank"] == 2

    async def test_leaderboard_ranks_pets_by_longest_streak(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Longest Streak category should rank pets by longest_streak descending."""
        from tests.conftest import test_session_factory

        _leaderboard_cache.clear()
        async with test_session_factory() as session:
            short_streak = Pet(
                repo_owner="org2", repo_name="short", name="ShortStreak", longest_streak=3
            )
            long_streak = Pet(
                repo_owner="org2", repo_name="long", name="LongStreak", longest_streak=42
            )
            session.add_all([short_streak, long_streak])
            await session.commit()

        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()

        streak_cat = next(c for c in data["categories"] if c["id"] == "longest_streak")
        assert streak_cat["entries"][0]["pet_name"] == "LongStreak"
        assert streak_cat["entries"][0]["value"] == 42

    async def test_leaderboard_excludes_opted_out_pets(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Pets with leaderboard_opt_out=True should not appear."""
        from tests.conftest import test_session_factory

        _leaderboard_cache.clear()
        async with test_session_factory() as session:
            opted_out = Pet(
                repo_owner="priv", repo_name="secret", name="HiddenPet",
                experience=9999, leaderboard_opt_out=True,
            )
            visible = Pet(
                repo_owner="pub", repo_name="open", name="VisiblePet",
                experience=1,
            )
            session.add_all([opted_out, visible])
            await session.commit()

        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()

        most_exp = next(c for c in data["categories"] if c["id"] == "most_experienced")
        names = [e["pet_name"] for e in most_exp["entries"]]
        assert "HiddenPet" not in names
        assert "VisiblePet" in names

    async def test_leaderboard_excludes_dead_pets(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Dead pets should not appear in the leaderboard."""
        from tests.conftest import test_session_factory

        _leaderboard_cache.clear()
        async with test_session_factory() as session:
            dead_pet = Pet(
                repo_owner="ghost", repo_name="dead", name="DeadPet",
                experience=8888, is_dead=True,
            )
            alive_pet = Pet(
                repo_owner="ghost", repo_name="alive", name="AlivePet",
                experience=10,
            )
            session.add_all([dead_pet, alive_pet])
            await session.commit()

        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()

        most_exp = next(c for c in data["categories"] if c["id"] == "most_experienced")
        names = [e["pet_name"] for e in most_exp["entries"]]
        assert "DeadPet" not in names
        assert "AlivePet" in names

    async def test_leaderboard_entry_links_to_pet_profile(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Each entry should expose repo_owner and repo_name for linking."""
        from tests.conftest import test_session_factory

        _leaderboard_cache.clear()
        async with test_session_factory() as session:
            pet = Pet(repo_owner="linktest", repo_name="myrepo", name="Linky", experience=500)
            session.add(pet)
            await session.commit()

        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()

        most_exp = next(c for c in data["categories"] if c["id"] == "most_experienced")
        entry = next(e for e in most_exp["entries"] if e["pet_name"] == "Linky")
        assert entry["repo_owner"] == "linktest"
        assert entry["repo_name"] == "myrepo"

    async def test_leaderboard_includes_cached_at(self, async_client: AsyncClient) -> None:
        """Response should include a cached_at timestamp."""
        _leaderboard_cache.clear()
        response = await async_client.get("/api/v1/leaderboard")
        data = response.json()
        assert "cached_at" in data


def _create_pet_for_leaderboard(
    repo_owner: str = "lbowner",
    repo_name: str = "lbrepo",
    name: str = "LBPet",
    experience: int = 500,
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                experience=experience,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


class TestLeaderboardHTMLPage:
    """Tests for the /leaderboard HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_leaderboard_title(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert "Leaderboard" in response.text

    def test_shows_most_experienced_section(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert "Most Experienced" in response.text

    def test_shows_longest_streak_section(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert "Longest Streak" in response.text

    def test_shows_pet_on_leaderboard(self, client: TestClient) -> None:
        _leaderboard_cache.clear()
        _create_pet_for_leaderboard(
            repo_owner="lbpageowner", repo_name="lbpagerepo", name="PagePet", experience=999
        )
        response = client.get("/leaderboard")
        assert "PagePet" in response.text

    def test_cache_control_header(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert "Cache-Control" in response.headers

    def test_shows_login_cta_when_unauthenticated(self, client: TestClient) -> None:
        response = client.get("/leaderboard")
        assert "Login" in response.text
