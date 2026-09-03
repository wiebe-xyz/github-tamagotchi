"""Tests for MCP server tools.

Every ownership-checked tool resolves the caller via
fastmcp.server.dependencies.get_access_token(), which relies on request-scoped
context that isn't present when calling a tool's underlying function (`.fn`)
directly. `_as_user()` below patches that resolution the same way the real
auth layer would populate it, so these stay fast unit tests of tool behavior
without needing a live server + real bearer token. See test_mcp_mount.py for
end-to-end tests that exercise the actual HTTP + token verification path.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.mcp.server import (
    check_pet_status,
    feed_pet,
    get_leaderboard,
    get_pet_history,
    how_to_play,
    list_pets,
    play_with_pet,
    register_pet,
    update_pet_from_repo,
)
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.services.github import RepoHealth
from github_tamagotchi.services.pet_feeding import FAT_THRESHOLD

# The @mcp.tool() decorator wraps functions in FunctionTool objects.
# Access the underlying function via .fn for direct testing.
_register_pet = register_pet.fn
_check_pet_status = check_pet_status.fn
_feed_pet = feed_pet.fn
_play_with_pet = play_with_pet.fn
_list_pets = list_pets.fn
_get_pet_history = get_pet_history.fn
_update_pet_from_repo = update_pet_from_repo.fn
_get_leaderboard = get_leaderboard.fn
_how_to_play = how_to_play.fn


@contextmanager
def _as_user(test_db: AsyncSession, user_id: int) -> Iterator[None]:
    """Run the wrapped block as an authenticated MCP call from `user_id`."""
    token = AccessToken(
        token="test-token",
        client_id=str(user_id),
        scopes=["pets:own"],
        claims={"user_id": user_id, "github_login": f"user{user_id}"},
    )
    with (
        patch("github_tamagotchi.mcp.server.async_session_factory") as mock_factory,
        patch("github_tamagotchi.mcp.server.get_access_token", return_value=token),
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        yield


@pytest.fixture
def mock_repo_health() -> RepoHealth:
    """Create a mock repository health object."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC),
        open_prs_count=2,
        oldest_pr_age_hours=24,
        open_issues_count=5,
        oldest_issue_age_days=3,
        last_ci_success=True,
        has_stale_dependencies=False,
    )


async def _make_pet(test_db: AsyncSession, user_id: int | None = 1, **overrides: object) -> Pet:
    defaults: dict[str, object] = {
        "repo_owner": "owner",
        "repo_name": "repo",
        "name": "TestPet",
        "stage": PetStage.BABY.value,
        "mood": PetMood.CONTENT.value,
        "health": 80,
        "experience": 50,
        "user_id": user_id,
    }
    defaults.update(overrides)
    pet = Pet(**defaults)  # type: ignore[arg-type]
    test_db.add(pet)
    await test_db.commit()
    await test_db.refresh(pet)
    return pet


class TestAuth:
    """Every ownership-checked tool must reject an unauthenticated call and
    a call against a pet the caller doesn't own."""

    async def test_check_pet_status_requires_auth(self, test_db: AsyncSession) -> None:
        with (
            patch("github_tamagotchi.mcp.server.async_session_factory") as mock_factory,
            patch("github_tamagotchi.mcp.server.get_access_token", return_value=None),
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            with pytest.raises(ToolError, match="[Nn]ot authenticated"):
                await _check_pet_status("owner", "repo")

    async def test_cannot_read_someone_elses_pet(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1)
        with _as_user(test_db, user_id=2), pytest.raises(ToolError, match="doesn't belong to you"):
            await _check_pet_status("owner", "repo")

    async def test_cannot_feed_someone_elses_pet(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1)
        with _as_user(test_db, user_id=2), pytest.raises(ToolError, match="doesn't belong to you"):
            await _feed_pet("owner", "repo")

    async def test_list_pets_only_shows_own(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1, repo_owner="a", repo_name="mine", name="Mine")
        await _make_pet(test_db, user_id=2, repo_owner="b", repo_name="theirs", name="Theirs")

        with _as_user(test_db, user_id=1):
            result = await _list_pets()

        names = [p["name"] for p in result["pets"]]
        assert names == ["Mine"]


class TestRegisterPet:
    """Tests for the register_pet MCP tool."""

    async def _user_with_token(self, test_db: AsyncSession, user_id: int = 1) -> User:
        user = User(
            id=user_id,
            github_id=user_id * 1000,
            github_login=f"user{user_id}",
            encrypted_token="encrypted-fake-token",
        )
        test_db.add(user)
        await test_db.commit()
        return user

    async def test_register_pet_creates_new_pet(self, test_db: AsyncSession) -> None:
        await self._user_with_token(test_db)
        with (
            _as_user(test_db, user_id=1),
            patch(
                "github_tamagotchi.mcp.server.decrypt_token", return_value="real-gh-token"
            ),
            patch(
                "github_tamagotchi.mcp.server._verify_github_repo_access",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await _register_pet("owner", "repo", "TestPet")

        assert "error" not in result
        assert result["pet"]["name"] == "TestPet"
        assert result["pet"]["stage"] == PetStage.EGG.value
        assert result["pet"]["health"] == 100
        assert "hatched" in result["message"]

    async def test_register_pet_rejects_repo_you_cant_access(
        self, test_db: AsyncSession
    ) -> None:
        """Can't register a pet for a repo you don't actually have access to."""
        await self._user_with_token(test_db)
        with (
            _as_user(test_db, user_id=1),
            patch(
                "github_tamagotchi.mcp.server.decrypt_token", return_value="real-gh-token"
            ),
            patch(
                "github_tamagotchi.mcp.server._verify_github_repo_access",
                new=AsyncMock(return_value=False),
            ),
            pytest.raises(ToolError, match="don't have access"),
        ):
            await _register_pet("someoneelse", "privaterepo", "TestPet")

    async def test_register_pet_requires_linked_github_token(
        self, test_db: AsyncSession
    ) -> None:
        user = User(id=1, github_id=1000, github_login="user1", encrypted_token=None)
        test_db.add(user)
        await test_db.commit()

        with _as_user(test_db, user_id=1), pytest.raises(
            ToolError, match="linked GitHub access token"
        ):
            await _register_pet("owner", "repo", "TestPet")

    async def test_register_pet_duplicate_fails(self, test_db: AsyncSession) -> None:
        await self._user_with_token(test_db)
        await _make_pet(test_db, user_id=1, name="ExistingPet")

        with (
            _as_user(test_db, user_id=1),
            patch(
                "github_tamagotchi.mcp.server.decrypt_token", return_value="real-gh-token"
            ),
            patch(
                "github_tamagotchi.mcp.server._verify_github_repo_access",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await _register_pet("owner", "repo", "AnotherPet")

        assert "error" in result
        assert "already exists" in result["error"]

    async def test_register_pet_rejects_malformed_repo_identifier(
        self, test_db: AsyncSession
    ) -> None:
        await self._user_with_token(test_db)
        with _as_user(test_db, user_id=1):
            result = await _register_pet("owner", "${ghUrl}", "TestPet")

        assert "error" in result
        assert "valid GitHub identifiers" in result["error"]

        from sqlalchemy import select

        rows = await test_db.execute(select(Pet).where(Pet.repo_name == "${ghUrl}"))
        assert rows.scalars().first() is None


class TestCheckPetStatus:
    """Tests for the check_pet_status MCP tool."""

    async def test_check_pet_status_returns_pet_info_and_ascii(
        self, test_db: AsyncSession, mock_repo_health: RepoHealth
    ) -> None:
        await _make_pet(
            test_db,
            user_id=1,
            name="TestPet",
            stage=PetStage.BABY.value,
            mood=PetMood.HAPPY.value,
            health=90,
            experience=150,
        )

        with (
            _as_user(test_db, user_id=1),
            patch("github_tamagotchi.mcp.server.GitHubService") as mock_github,
        ):
            mock_github.return_value.get_repo_health = AsyncMock(return_value=mock_repo_health)
            result = await _check_pet_status("owner", "repo")

        assert "error" not in result
        assert result["pet"]["name"] == "TestPet"
        assert result["pet"]["stage"] == PetStage.BABY.value
        assert result["health_metrics"]["ci_passing"] is True
        assert result["ascii_art"]  # non-empty fallback art, no storage configured in tests

    async def test_check_pet_status_no_pet(self, test_db: AsyncSession) -> None:
        with _as_user(test_db, user_id=1), pytest.raises(ToolError, match="No pet found"):
            await _check_pet_status("owner", "nonexistent")


class TestFeedPet:
    """Tests for the feed_pet MCP tool and the overfeeding mechanic."""

    async def test_feed_pet_increases_health_and_weight(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1, mood=PetMood.HUNGRY.value, health=80)

        with _as_user(test_db, user_id=1):
            result = await _feed_pet("owner", "repo")

        assert "error" not in result
        assert result["pet"]["health"] == 83
        assert result["health_change"] == 3
        assert result["overfed"] is False

    async def test_feed_pet_caps_health_at_100(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1, health=99)

        with _as_user(test_db, user_id=1):
            result = await _feed_pet("owner", "repo")

        assert result["pet"]["health"] == 100
        assert result["health_change"] == 1

    async def test_overfeeding_makes_pet_fat_and_stops_helping(
        self, test_db: AsyncSession
    ) -> None:
        """Repeated feeding gives diminishing, then zero, benefit once fat."""
        pet = await _make_pet(test_db, user_id=1, health=50, weight=FAT_THRESHOLD - 1)

        with _as_user(test_db, user_id=1):
            # This call pushes weight over the fat threshold.
            first = await _feed_pet("owner", "repo")
            assert first["overfed"] is False
            assert first["health_change"] > 0

            # Now fat — feeding again should do nothing for health.
            second = await _feed_pet("owner", "repo")
            assert second["overfed"] is True
            assert second["health_change"] == 0
            assert second["pet"]["weight"] == "fat"

        await test_db.refresh(pet)
        assert pet.weight > FAT_THRESHOLD

    async def test_feed_pet_no_pet(self, test_db: AsyncSession) -> None:
        with _as_user(test_db, user_id=1), pytest.raises(ToolError, match="No pet found"):
            await _feed_pet("owner", "nonexistent")


class TestPlayWithPet:
    """Tests for the play_with_pet MCP tool.

    play_with_pet's cooldown tracker is module-level, in-process state keyed
    by pet id — see the global `_reset_mcp_play_cooldowns` autouse fixture in
    conftest.py, which clears it before every test in the suite.
    """

    async def test_play_with_pet_returns_ascii_and_cheers_up(
        self, test_db: AsyncSession
    ) -> None:
        await _make_pet(test_db, user_id=1, mood=PetMood.WORRIED.value)

        with _as_user(test_db, user_id=1):
            result = await _play_with_pet("owner", "repo")

        assert result["ascii_art"]
        assert result["cheered_up"] is True
        assert result["pet"]["mood"] == PetMood.CONTENT.value

    async def test_play_with_pet_is_rate_limited(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1, mood=PetMood.WORRIED.value)

        with _as_user(test_db, user_id=1):
            first = await _play_with_pet("owner", "repo")
            second = await _play_with_pet("owner", "repo")

        assert first["cheered_up"] is True
        assert second["cheered_up"] is False
        assert "note" in second

    async def test_play_with_pet_caps_below_dancing(self, test_db: AsyncSession) -> None:
        await _make_pet(test_db, user_id=1, mood=PetMood.HAPPY.value)

        with _as_user(test_db, user_id=1):
            result = await _play_with_pet("owner", "repo")

        assert result["pet"]["mood"] == PetMood.HAPPY.value
        assert result["cheered_up"] is False


class TestListPets:
    """Tests for the list_pets MCP tool."""

    async def test_list_pets_empty(self, test_db: AsyncSession) -> None:
        with _as_user(test_db, user_id=1):
            result = await _list_pets()

        assert result["pets"] == []
        assert result["count"] == 0

    async def test_list_pets_returns_own_pets(self, test_db: AsyncSession) -> None:
        await _make_pet(
            test_db, user_id=1, repo_owner="owner1", repo_name="repo1", name="Pet1"
        )
        await _make_pet(
            test_db,
            user_id=1,
            repo_owner="owner2",
            repo_name="repo2",
            name="Pet2",
            stage=PetStage.ADULT.value,
            experience=5000,
        )

        with _as_user(test_db, user_id=1):
            result = await _list_pets()

        assert result["count"] == 2
        names = [p["name"] for p in result["pets"]]
        assert "Pet1" in names
        assert "Pet2" in names


class TestGetPetHistory:
    """Tests for the get_pet_history MCP tool."""

    async def test_get_pet_history_shows_evolution(self, test_db: AsyncSession) -> None:
        await _make_pet(
            test_db,
            user_id=1,
            stage=PetStage.TEEN.value,
            mood=PetMood.HAPPY.value,
            health=100,
            experience=2000,
        )

        with _as_user(test_db, user_id=1):
            result = await _get_pet_history("owner", "repo")

        assert "error" not in result
        assert result["pet"]["current_stage"] == PetStage.TEEN.value
        assert PetStage.EGG.value in result["evolution"]["stages_completed"]
        assert PetStage.BABY.value in result["evolution"]["stages_completed"]
        assert PetStage.ADULT.value in result["evolution"]["stages_remaining"]

    async def test_get_pet_history_no_pet(self, test_db: AsyncSession) -> None:
        with _as_user(test_db, user_id=1), pytest.raises(ToolError, match="No pet found"):
            await _get_pet_history("owner", "nonexistent")


class TestUpdatePetFromRepo:
    """Tests for the update_pet_from_repo MCP tool."""

    async def test_update_pet_from_repo(
        self, test_db: AsyncSession, mock_repo_health: RepoHealth
    ) -> None:
        await _make_pet(
            test_db, user_id=1, health=50, experience=100, weight=60.0
        )

        with (
            _as_user(test_db, user_id=1),
            patch("github_tamagotchi.mcp.server.GitHubService") as mock_github,
        ):
            mock_github.return_value.get_repo_health = AsyncMock(return_value=mock_repo_health)
            result = await _update_pet_from_repo("owner", "repo")

        assert "error" not in result
        assert "changes" in result
        assert result["pet"]["mood"] == PetMood.DANCING.value
        assert result["changes"]["weight_lost"] == 10.0
        assert result["pet"]["weight"] == "trim"

    async def test_update_pet_from_repo_no_pet(self, test_db: AsyncSession) -> None:
        with _as_user(test_db, user_id=1), pytest.raises(ToolError, match="No pet found"):
            await _update_pet_from_repo("owner", "nonexistent")


class TestGetLeaderboard:
    """Tests for the get_leaderboard MCP tool — the one cross-user read."""

    async def test_shows_other_users_pets_ranked_by_experience(
        self, test_db: AsyncSession
    ) -> None:
        await _make_pet(
            test_db, user_id=1, repo_owner="a", repo_name="low", name="Low", experience=10
        )
        await _make_pet(
            test_db, user_id=2, repo_owner="b", repo_name="high", name="High", experience=9000
        )

        with _as_user(test_db, user_id=1):
            result = await _get_leaderboard()

        names = [p["name"] for p in result["leaderboard"]]
        assert names[0] == "High"
        assert "Low" in names

    async def test_excludes_opted_out_pets(self, test_db: AsyncSession) -> None:
        await _make_pet(
            test_db,
            user_id=2,
            repo_owner="b",
            repo_name="hidden",
            name="Hidden",
            experience=9000,
            leaderboard_opt_out=True,
        )

        with _as_user(test_db, user_id=1):
            result = await _get_leaderboard()

        names = [p["name"] for p in result["leaderboard"]]
        assert "Hidden" not in names


class TestHowToPlay:
    def test_returns_instructions(self) -> None:
        text = _how_to_play()
        assert "GitHub Tamagotchi" in text
        assert "feed_pet" in text
