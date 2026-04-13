"""Tests for the pet profile and pet admin HTML pages."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from tests.conftest import test_session_factory


@contextmanager
def _as_admin(login: str) -> Iterator[None]:
    """Patch settings so the given login is treated as admin."""
    with patch(
        "github_tamagotchi.api.auth.settings.admin_github_logins",
        new=[login],
    ), patch(
        "github_tamagotchi.main.settings.admin_github_logins",
        new=[login],
    ):
        yield


def _create_pet(
    repo_owner: str = "testowner",
    repo_name: str = "testrepo",
    name: str = "Gotchi",
    stage: str = PetStage.BABY.value,
    mood: str = PetMood.HAPPY.value,
    health: int = 80,
    experience: int = 150,
    grace_period_started: datetime | None = None,
    is_dead: bool = False,
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
                grace_period_started=grace_period_started,
                is_dead=is_dead,
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

    def test_dying_banner_shown_when_in_grace_period(self, client: TestClient) -> None:
        """Profile page shows dying banner when pet health is 0 and grace period is active."""
        grace_start = datetime.now(UTC) - timedelta(days=2)
        _create_pet(
            repo_owner="dyingowner",
            repo_name="dyingrepo",
            health=0,
            grace_period_started=grace_start,
        )
        response = client.get("/pet/dyingowner/dyingrepo")
        assert response.status_code == 200
        assert "Critical condition" in response.text
        assert "will die in" in response.text

    def test_dying_banner_not_shown_when_healthy(self, client: TestClient) -> None:
        """Profile page does not show dying banner for healthy pets."""
        _create_pet(repo_owner="healthyowner", repo_name="healthyrepo", health=80)
        response = client.get("/pet/healthyowner/healthyrepo")
        assert "Critical condition" not in response.text

    def test_dying_banner_not_shown_when_dead(self, client: TestClient) -> None:
        """Profile page does not show dying banner for dead pets."""
        grace_start = datetime.now(UTC) - timedelta(days=10)
        _create_pet(
            repo_owner="deadowner",
            repo_name="deadrepo",
            health=0,
            grace_period_started=grace_start,
            is_dead=True,
        )
        response = client.get("/pet/deadowner/deadrepo")
        assert "Critical condition" not in response.text

    def test_dying_banner_shows_days_remaining(self, client: TestClient) -> None:
        """Dying banner shows correct days remaining."""
        grace_start = datetime.now(UTC) - timedelta(days=4)
        _create_pet(
            repo_owner="countdownowner",
            repo_name="countdownrepo",
            health=0,
            grace_period_started=grace_start,
        )
        response = client.get("/pet/countdownowner/countdownrepo")
        assert "3 days" in response.text

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


def _create_user_with_pet(
    user_id: int,
    github_login: str,
    repo_owner: str,
    repo_name: str,
    encrypted_token: str | None = None,
) -> str:
    async def _setup() -> str:
        async with test_session_factory() as session:
            user = User(
                id=user_id,
                github_id=user_id * 1000,
                github_login=github_login,
                github_avatar_url=None,
                encrypted_token=encrypted_token,
            )
            session.add(user)
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name="AdminPet",
                user_id=user_id,
            )
            session.add(pet)
            await session.commit()
        return _create_jwt(user_id=user_id)

    return asyncio.run(_setup())


class TestPetAdminHTMLPage:
    """Tests for /pet/{owner}/{repo}/admin HTML page."""

    def test_unauthenticated_redirects_to_auth(self, client: TestClient) -> None:
        _create_pet(repo_owner="adminpageowner", repo_name="adminpagerepo", name="AdminPet")
        response = client.get("/pet/adminpageowner/adminpagerepo/admin", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/github" in response.headers["location"]

    def test_not_found_returns_404(self, client: TestClient) -> None:
        token = _create_user_with_pet(
            user_id=200,
            github_login="adminloginpet200",
            repo_owner="adminloginpet200",
            repo_name="somerepo200",
        )
        with _as_admin("adminloginpet200"):
            response = client.get("/pet/nobody/nonexistent/admin", cookies={"session_token": token})
        assert response.status_code == 404

    def test_non_admin_user_without_token_gets_403(self, client: TestClient) -> None:
        token = _create_user_with_pet(
            user_id=201,
            github_login="regularuser201",
            repo_owner="adminpageowner201",
            repo_name="adminpagerepo201",
            encrypted_token=None,
        )
        response = client.get(
            "/pet/adminpageowner201/adminpagerepo201/admin",
            cookies={"session_token": token},
        )
        assert response.status_code == 403

    def test_site_admin_can_access_any_pet_admin(self, client: TestClient) -> None:
        token = _create_user_with_pet(
            user_id=202,
            github_login="siteadminlogin202",
            repo_owner="siteadminlogin202",
            repo_name="adminpagerepo202",
        )
        with _as_admin("siteadminlogin202"):
            response = client.get(
                "/pet/siteadminlogin202/adminpagerepo202/admin",
                cookies={"session_token": token},
            )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_repo_admin_via_token_can_access(self, client: TestClient) -> None:
        token = _create_user_with_pet(
            user_id=203,
            github_login="repoadmin203",
            repo_owner="repoadmin203",
            repo_name="repoadminrepo203",
            encrypted_token="fake-encrypted-token",
        )
        with patch(
            "github_tamagotchi.services.token_encryption.decrypt_token",
            return_value="decrypted-token",
        ), patch(
            "github_tamagotchi.main.GitHubService.get_repo_permission",
            new_callable=AsyncMock,
            return_value="admin",
        ):
            response = client.get(
                "/pet/repoadmin203/repoadminrepo203/admin",
                cookies={"session_token": token},
            )
        assert response.status_code == 200
