"""Tests for the pet profile page."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from tests.conftest import test_session_factory


def _create_pet(
    repo_owner: str = "testowner",
    repo_name: str = "testrepo",
    name: str = "Gotchi",
    stage: str = PetStage.BABY.value,
    mood: str = PetMood.HAPPY.value,
    health: int = 80,
    experience: int = 150,
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                stage=stage,
                mood=mood,
                health=health,
                experience=experience,
                created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


class TestPetProfilePage:
    """Tests for /pet/{owner}/{repo} page."""

    def test_returns_html(self, client: TestClient) -> None:
        """Profile page should return HTML."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_pet_name(self, client: TestClient) -> None:
        """Profile page should show the pet's name."""
        _create_pet(name="Gotchi")
        response = client.get("/pet/testowner/testrepo")
        assert "Gotchi" in response.text

    def test_contains_repo_owner_and_name(self, client: TestClient) -> None:
        """Profile page should show owner/repo."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "testowner" in response.text
        assert "testrepo" in response.text

    def test_contains_stage(self, client: TestClient) -> None:
        """Profile page should show the stage."""
        _create_pet(stage=PetStage.BABY.value)
        response = client.get("/pet/testowner/testrepo")
        assert "Baby" in response.text

    def test_contains_health(self, client: TestClient) -> None:
        """Profile page should show health stat."""
        _create_pet(health=75)
        response = client.get("/pet/testowner/testrepo")
        assert "75%" in response.text

    def test_contains_experience(self, client: TestClient) -> None:
        """Profile page should show experience stat."""
        _create_pet(experience=200)
        response = client.get("/pet/testowner/testrepo")
        assert "200" in response.text

    def test_contains_mood(self, client: TestClient) -> None:
        """Profile page should show pet mood."""
        _create_pet(mood=PetMood.HAPPY.value)
        response = client.get("/pet/testowner/testrepo")
        assert "Happy" in response.text

    def test_contains_evolution_timeline(self, client: TestClient) -> None:
        """Profile page should show evolution timeline."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "Evolution Timeline" in response.text
        assert "Egg" in response.text
        assert "Elder" in response.text

    def test_contains_activity_section(self, client: TestClient) -> None:
        """Profile page should show activity section."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "Recent Activity" in response.text

    def test_contains_get_your_own_cta_when_unauthenticated(self, client: TestClient) -> None:
        """Unauthenticated visitors should see the 'Get your own pet' CTA."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "Get your own pet" in response.text

    def test_contains_share_buttons(self, client: TestClient) -> None:
        """Profile page should have share buttons."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "Share" in response.text
        assert "Copy link" in response.text

    def test_has_og_meta_tags(self, client: TestClient) -> None:
        """Profile page should include OpenGraph meta tags."""
        _create_pet(name="Gotchi")
        response = client.get("/pet/testowner/testrepo")
        assert 'property="og:title"' in response.text
        assert 'property="og:description"' in response.text
        assert 'property="og:image"' in response.text

    def test_has_twitter_card_meta_tags(self, client: TestClient) -> None:
        """Profile page should include Twitter Card meta tags."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert 'name="twitter:card"' in response.text
        assert 'name="twitter:title"' in response.text

    def test_meta_tags_use_absolute_urls_with_badge_svg(self, client: TestClient) -> None:
        """Profile page meta image tags should use absolute URLs pointing to the badge SVG."""
        _create_pet(repo_owner="testowner", repo_name="testrepo")
        response = client.get("/pet/testowner/testrepo")
        assert response.status_code == 200
        # og:image must point to badge.svg (not image endpoint), with an absolute URL
        assert "/api/v1/pets/testowner/testrepo/badge.svg" in response.text
        # og:url must be an absolute URL (starts with http)
        og_url_line = next(
            (line for line in response.text.splitlines() if 'property="og:url"' in line),
            "",
        )
        assert "http" in og_url_line

    def test_not_found_returns_404(self, client: TestClient) -> None:
        """Non-existent pet should return 404."""
        response = client.get("/pet/nobody/nonexistent")
        assert response.status_code == 404

    def test_cache_control_header(self, client: TestClient) -> None:
        """Profile page should include cache control header."""
        _create_pet()
        response = client.get("/pet/testowner/testrepo")
        assert "Cache-Control" in response.headers

    def test_no_get_your_own_cta_when_authenticated(self, client: TestClient) -> None:
        """Authenticated users should not see the 'Get your own pet' CTA."""
        from github_tamagotchi.api.auth import _create_jwt
        from github_tamagotchi.models.user import User

        async def _setup_user() -> str:
            async with test_session_factory() as session:
                user = User(
                    id=99,
                    github_id=99999,
                    github_login="profiletestuser",
                )
                session.add(user)
                await session.commit()
            return _create_jwt(user_id=99)

        _create_pet()
        token = asyncio.run(_setup_user())
        response = client.get("/pet/testowner/testrepo", cookies={"session_token": token})
        assert response.status_code == 200
        assert "Get your own pet" not in response.text
