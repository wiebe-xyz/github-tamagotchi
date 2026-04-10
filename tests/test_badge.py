"""Tests for SVG badge generation."""

import base64
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from github_tamagotchi.services.badge import (
    BADGE_STYLES,
    DEFAULT_BADGE_STYLE,
    MOOD_ANIMATION,
    ContributorStanding,
    generate_badge_svg,
    generate_contributor_badge_svg,
)

# A minimal 1x1 transparent PNG, base64-encoded, used as a stand-in sprite in tests.
_DUMMY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
_DUMMY_B64 = base64.b64encode(_DUMMY_PNG_BYTES).decode()


class TestGenerateBadgeSvg:
    """Unit tests for the SVG badge generator."""

    def test_returns_valid_svg(self) -> None:
        """Output must be a valid SVG string."""
        svg = generate_badge_svg("MyPet", "egg", "content", 100)
        assert svg.strip().startswith("<svg")
        assert "</svg>" in svg

    def test_contains_pet_name(self) -> None:
        """Badge includes the pet's name."""
        svg = generate_badge_svg("Chompy", "baby", "happy", 80)
        assert "Chompy" in svg

    def test_contains_stage_label(self) -> None:
        """Badge includes the stage label."""
        svg = generate_badge_svg("Chompy", "adult", "content", 75)
        assert "Adult" in svg

    def test_contains_stage_sprite(self) -> None:
        """Badge includes the emoji sprite for the stage when no image is provided."""
        svg = generate_badge_svg("X", "egg", "content", 100)
        assert "🥚" in svg

        svg = generate_badge_svg("X", "elder", "content", 100)
        assert "🦅" in svg

    def test_contains_mood_sprite(self) -> None:
        """Badge includes the emoji for the mood when no image is provided."""
        svg = generate_badge_svg("X", "adult", "sick", 30)
        assert "🤒" in svg

    def test_health_bar_reflects_value(self) -> None:
        """Health bar width is proportional to health value."""
        svg_full = generate_badge_svg("X", "egg", "content", 100)
        svg_low = generate_badge_svg("X", "egg", "content", 10)
        # Full health: width=65; 10% health: width=6
        assert 'width="65"' in svg_full
        assert 'width="6"' in svg_low

    def test_health_clamped(self) -> None:
        """Health below 0 or above 100 is clamped."""
        svg_over = generate_badge_svg("X", "egg", "content", 200)
        assert 'width="65"' in svg_over  # clamped to 100 → width 65

        svg_under = generate_badge_svg("X", "egg", "content", -10)
        assert 'width="0"' in svg_under

    def test_long_name_truncated(self) -> None:
        """Very long names are truncated to fit the badge."""
        long_name = "A" * 20
        svg = generate_badge_svg(long_name, "egg", "content", 100)
        # Full name should not appear; truncated version should
        assert long_name not in svg
        assert "…" in svg

    def test_unknown_stage_fallback(self) -> None:
        """Unknown stage falls back to egg sprite."""
        svg = generate_badge_svg("X", "unknown_stage", "content", 100)
        assert "🥚" in svg

    def test_unknown_mood_fallback(self) -> None:
        """Unknown mood falls back to content sprite."""
        svg = generate_badge_svg("X", "egg", "unknown_mood", 100)
        assert "😌" in svg

    # --- Sprite image tests ---

    def test_with_image_embeds_base64(self) -> None:
        """When a base64 image is provided, SVG embeds it as a data URI."""
        svg = generate_badge_svg("Pixel", "adult", "happy", 80, pet_image_b64=_DUMMY_B64)
        assert "data:image/png;base64," in svg
        assert _DUMMY_B64 in svg

    def test_with_image_wider_badge(self) -> None:
        """Badge with sprite is wider than emoji badge."""
        svg_emoji = generate_badge_svg("X", "egg", "content", 100)
        svg_sprite = generate_badge_svg("X", "egg", "content", 100, pet_image_b64=_DUMMY_B64)
        assert 'width="120"' in svg_emoji
        assert 'width="160"' in svg_sprite

    def test_with_image_no_stage_emoji_in_sprite_position(self) -> None:
        """When sprite is embedded, stage emoji is not used as the sprite element."""
        svg = generate_badge_svg("X", "egg", "content", 100, pet_image_b64=_DUMMY_B64)
        # The data URI replaces the emoji; the egg emoji should not appear
        assert "🥚" not in svg

    def test_with_image_has_animation_keyframes(self) -> None:
        """Badge with sprite includes CSS keyframe animations."""
        svg = generate_badge_svg("X", "adult", "happy", 80, pet_image_b64=_DUMMY_B64)
        assert "@keyframes" in svg
        assert "bounce" in svg

    def test_mood_animation_happy_bounce(self) -> None:
        """happy mood uses bounce animation."""
        svg = generate_badge_svg("X", "adult", "happy", 80, pet_image_b64=_DUMMY_B64)
        assert "bounce" in svg
        assert "animation:bounce" in svg

    def test_mood_animation_dancing_bounce(self) -> None:
        """dancing mood uses bounce animation."""
        svg = generate_badge_svg("X", "adult", "dancing", 80, pet_image_b64=_DUMMY_B64)
        assert "bounce" in svg

    def test_mood_animation_content_float(self) -> None:
        """content mood uses float animation."""
        svg = generate_badge_svg("X", "adult", "content", 80, pet_image_b64=_DUMMY_B64)
        assert "float" in svg
        assert "animation:float" in svg

    def test_mood_animation_hungry_shake(self) -> None:
        """hungry mood uses shake animation."""
        svg = generate_badge_svg("X", "adult", "hungry", 80, pet_image_b64=_DUMMY_B64)
        assert "shake" in svg
        assert "animation:shake" in svg

    def test_mood_animation_sick_pulse(self) -> None:
        """sick mood uses pulse animation."""
        svg = generate_badge_svg("X", "adult", "sick", 30, pet_image_b64=_DUMMY_B64)
        assert "pulse" in svg
        assert "animation:pulse" in svg

    def test_mood_animation_lonely_pulse(self) -> None:
        """lonely mood uses pulse animation."""
        svg = generate_badge_svg("X", "adult", "lonely", 40, pet_image_b64=_DUMMY_B64)
        assert "pulse" in svg

    def test_without_image_shows_emoji_fallback(self) -> None:
        """Without an image, badge uses emoji and is 120px wide."""
        svg = generate_badge_svg("X", "adult", "happy", 80)
        assert "😊" in svg
        assert 'width="120"' in svg
        assert "data:image/png;base64," not in svg

    def test_mood_label_shown_with_sprite(self) -> None:
        """Mood text label is shown in the right column when sprite is embedded."""
        svg = generate_badge_svg("X", "adult", "dancing", 80, pet_image_b64=_DUMMY_B64)
        assert "Dancing" in svg

    def test_dead_pet_with_image_greyscale(self) -> None:
        """Deceased pet with sprite applies greyscale filter."""
        svg = generate_badge_svg(
            "Ghost", "adult", "content", 0,
            is_dead=True,
            pet_image_b64=_DUMMY_B64,
        )
        assert "feColorMatrix" in svg
        assert 'values="0"' in svg
        assert "data:image/png;base64," in svg

    def test_dead_pet_without_image_uses_tombstone(self) -> None:
        """Deceased pet without sprite still shows tombstone emoji."""
        svg = generate_badge_svg("Ghost", "adult", "content", 0, is_dead=True)
        assert "🪦" in svg

    def test_sprite_health_bar_uses_72px_scale(self) -> None:
        """Sprite badge health bar uses 72px max width scale."""
        svg = generate_badge_svg("X", "adult", "content", 100, pet_image_b64=_DUMMY_B64)
        assert 'width="72"' in svg  # 100 * 0.72 = 72

        svg_half = generate_badge_svg("X", "adult", "content", 50, pet_image_b64=_DUMMY_B64)
        assert 'width="36"' in svg_half  # 50 * 0.72 = 36

    def test_mood_animation_coverage(self) -> None:
        """Every mood in MOOD_ANIMATION maps to a known animation name."""
        known = {"bounce", "float", "shake", "pulse"}
        for mood, (anim_name, _) in MOOD_ANIMATION.items():
            assert anim_name in known, f"Unknown animation '{anim_name}' for mood '{mood}'"


class TestBadgeEndpoint:
    """Integration tests for the badge SVG endpoint."""

    async def test_badge_returns_200(self, async_client: AsyncClient) -> None:
        """Badge endpoint returns 200 for an existing pet."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "user", "repo_name": "repo", "name": "Fluffy"},
        )

        response = await async_client.get("/api/v1/pets/user/repo/badge.svg")
        assert response.status_code == 200

    async def test_badge_content_type(self, async_client: AsyncClient) -> None:
        """Badge endpoint returns SVG content type."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "user", "repo_name": "repo", "name": "Fluffy"},
        )

        response = await async_client.get("/api/v1/pets/user/repo/badge.svg")
        assert "image/svg+xml" in response.headers["content-type"]

    async def test_badge_cache_headers(self, async_client: AsyncClient) -> None:
        """Badge endpoint includes proper cache headers."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "user", "repo_name": "repo", "name": "Fluffy"},
        )

        response = await async_client.get("/api/v1/pets/user/repo/badge.svg")
        assert "cache-control" in response.headers
        assert "public" in response.headers["cache-control"]
        assert "max-age" in response.headers["cache-control"]

    async def test_badge_returns_valid_svg(self, async_client: AsyncClient) -> None:
        """Badge endpoint body is valid SVG."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "user", "repo_name": "repo", "name": "Buddy"},
        )

        response = await async_client.get("/api/v1/pets/user/repo/badge.svg")
        body = response.text
        assert body.strip().startswith("<svg")
        assert "</svg>" in body
        assert "Buddy" in body

    async def test_badge_not_found(self, async_client: AsyncClient) -> None:
        """Badge endpoint returns 404 when pet does not exist."""
        response = await async_client.get("/api/v1/pets/nobody/norepo/badge.svg")
        assert response.status_code == 404

    async def test_badge_falls_back_to_emoji_when_no_image(self, async_client: AsyncClient) -> None:
        """Badge endpoint returns emoji-based SVG when no sprite is in storage."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "imgtest", "repo_name": "repo", "name": "NoPic"},
        )

        response = await async_client.get("/api/v1/pets/imgtest/repo/badge.svg")
        assert response.status_code == 200
        # No image in MinIO for test pets → emoji fallback → 120px wide badge
        body = response.text
        assert body.strip().startswith("<svg")
        # Emoji fallback badge is 120px wide
        assert 'width="120"' in body

    async def test_style_query_param_minimal(self, async_client: AsyncClient) -> None:
        """?style=minimal returns a minimal badge regardless of stored badge_style."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "styletest", "repo_name": "repo", "name": "Stylish"},
        )

        response = await async_client.get("/api/v1/pets/styletest/repo/badge.svg?style=minimal")
        assert response.status_code == 200
        body = response.text
        assert body.strip().startswith("<svg")
        # Minimal badge is 120px wide and 60px tall
        assert 'width="120"' in body
        assert 'height="60"' in body

    async def test_style_query_param_maintained(self, async_client: AsyncClient) -> None:
        """?style=maintained returns a shields.io-style maintained badge."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "styletest2", "repo_name": "repo", "name": "Trusty"},
        )

        response = await async_client.get("/api/v1/pets/styletest2/repo/badge.svg?style=maintained")
        assert response.status_code == 200
        body = response.text
        assert body.strip().startswith("<svg")
        # Maintained badge is 20px tall (shields.io style)
        assert 'height="20"' in body

    async def test_style_query_param_playful(self, async_client: AsyncClient) -> None:
        """?style=playful returns the default playful badge."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "styletest3", "repo_name": "repo", "name": "Funky"},
        )

        response = await async_client.get("/api/v1/pets/styletest3/repo/badge.svg?style=playful")
        assert response.status_code == 200
        body = response.text
        assert body.strip().startswith("<svg")
        assert 'height="80"' in body

    async def test_style_query_param_invalid_returns_422(self, async_client: AsyncClient) -> None:
        """?style=unknown returns 422 Unprocessable Entity."""
        response = await async_client.get("/api/v1/pets/anyone/repo/badge.svg?style=kawaii")
        assert response.status_code == 422

    async def test_style_query_param_overrides_stored_style(
        self, async_client: AsyncClient
    ) -> None:
        """?style= overrides the pet's stored badge_style."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "overridetest", "repo_name": "repo", "name": "Override"},
        )

        # Default style is playful (80px tall) — override with maintained (20px tall)
        response = await async_client.get(
            "/api/v1/pets/overridetest/repo/badge.svg?style=maintained"
        )
        assert response.status_code == 200
        assert 'height="20"' in response.text


class TestBadgeStyles:
    """Tests for the three badge style variants."""

    def test_default_badge_style_is_playful(self) -> None:
        assert DEFAULT_BADGE_STYLE == "playful"

    def test_badge_styles_set_contains_all_three(self) -> None:
        assert {"playful", "minimal", "maintained"} == BADGE_STYLES

    def test_playful_style_returns_svg(self) -> None:
        svg = generate_badge_svg("Fluffy", "egg", "content", 80, badge_style="playful")
        assert svg.strip().startswith("<svg")
        assert "Fluffy" in svg

    def test_minimal_style_returns_svg(self) -> None:
        svg = generate_badge_svg("Fluffy", "egg", "content", 80, badge_style="minimal")
        assert svg.strip().startswith("<svg")
        assert "Fluffy" in svg

    def test_maintained_style_returns_svg(self) -> None:
        svg = generate_badge_svg("Fluffy", "egg", "content", 80, badge_style="maintained")
        assert svg.strip().startswith("<svg")
        assert "Fluffy" in svg

    def test_minimal_dead_badge(self) -> None:
        svg = generate_badge_svg(
            "Ghost", "egg", "content", 0, is_dead=True, badge_style="minimal"
        )
        assert "Deceased" in svg

    def test_maintained_dead_badge(self) -> None:
        svg = generate_badge_svg(
            "Ghost", "egg", "content", 0, is_dead=True, badge_style="maintained"
        )
        assert "deceased" in svg

    def test_maintained_healthy_shows_healthy(self) -> None:
        svg = generate_badge_svg("A", "adult", "happy", 90, badge_style="maintained")
        assert "healthy" in svg

    def test_maintained_critical_shows_critical(self) -> None:
        svg = generate_badge_svg("A", "adult", "sick", 20, badge_style="maintained")
        assert "critical" in svg

    def test_unknown_badge_style_falls_back_to_playful(self) -> None:
        """Unrecognised badge_style falls back to playful layout."""
        svg_playful = generate_badge_svg("X", "egg", "content", 50, badge_style="playful")
        svg_unknown = generate_badge_svg("X", "egg", "content", 50, badge_style="unknown")
        assert svg_playful == svg_unknown


class TestGenerateContributorBadgeSvg:
    """Unit tests for the contributor badge SVG generator."""

    def test_returns_valid_svg(self) -> None:
        """Output must be a valid SVG string."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.NEUTRAL
        )
        assert svg.strip().startswith("<svg")
        assert "</svg>" in svg

    def test_favorite_standing_shows_star(self) -> None:
        """Favorite standing includes the star label."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.FAVORITE
        )
        assert "Favorite Human" in svg

    def test_good_standing_shows_score(self) -> None:
        """Good standing with score shows point count."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.GOOD, score=127
        )
        assert "127 pts" in svg

    def test_absent_standing_shows_days(self) -> None:
        """Absent standing shows days away."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.ABSENT, days_away=23
        )
        assert "23d away" in svg

    def test_doghouse_standing_default_detail(self) -> None:
        """Doghouse standing shows default shame text when no detail provided."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.DOGHOUSE
        )
        assert "Fix your PR!" in svg

    def test_doghouse_standing_custom_detail(self) -> None:
        """Doghouse standing shows custom shame detail when provided."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "charlie", ContributorStanding.DOGHOUSE,
            shame_detail="Broke CI 2d ago",
        )
        assert "Broke CI 2d ago" in svg

    def test_contains_username(self) -> None:
        """Badge includes the contributor's username."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "alice", ContributorStanding.GOOD
        )
        assert "alice" in svg

    def test_contains_pet_name(self) -> None:
        """Badge includes the pet's name."""
        svg = generate_contributor_badge_svg(
            "Chippy", "baby", "alice", ContributorStanding.GOOD
        )
        assert "Chippy" in svg

    def test_long_pet_name_truncated(self) -> None:
        """Very long pet names are truncated to keep badge width manageable."""
        long_name = "A" * 20
        svg = generate_contributor_badge_svg(
            long_name, "baby", "alice", ContributorStanding.NEUTRAL
        )
        assert long_name not in svg
        assert "…" in svg

    def test_all_standings_produce_valid_svg(self) -> None:
        """All standing variants produce valid SVG."""
        for standing in ContributorStanding:
            svg = generate_contributor_badge_svg("Pet", "baby", "user", standing)
            assert svg.strip().startswith("<svg"), f"Invalid SVG for standing {standing}"
            assert "</svg>" in svg


class TestContributorBadgeEndpoint:
    """Integration tests for the contributor badge endpoint."""

    async def test_contributor_badge_not_found(self, async_client: AsyncClient) -> None:
        """Returns 404 when the pet does not exist."""
        response = await async_client.get("/api/v1/contributor/nobody/norepo/charlie.svg")
        assert response.status_code == 404

    async def test_contributor_badge_returns_svg(self, async_client: AsyncClient) -> None:
        """Endpoint returns valid SVG for an existing pet."""
        from datetime import UTC, datetime

        from github_tamagotchi.services.github import ContributorStats

        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "myrepo", "name": "Chippy"},
        )

        mock_stats = ContributorStats(
            commits_30d=5,
            last_commit_at=datetime.now(UTC),
            is_top_contributor=True,
            has_failed_ci=False,
            days_since_last_commit=0,
        )

        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=mock_stats,
        ):
            response = await async_client.get("/api/v1/contributor/owner/myrepo/charlie.svg")

        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]
        body = response.text
        assert body.strip().startswith("<svg")
        assert "Chippy" in body

    async def test_contributor_badge_favorite_standing(self, async_client: AsyncClient) -> None:
        """Top contributor gets favorite standing badge."""
        from datetime import UTC, datetime

        from github_tamagotchi.services.github import ContributorStats

        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner2", "repo_name": "myrepo2", "name": "Fluffy"},
        )

        mock_stats = ContributorStats(
            commits_30d=10,
            last_commit_at=datetime.now(UTC),
            is_top_contributor=True,
            has_failed_ci=False,
            days_since_last_commit=0,
        )

        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=mock_stats,
        ):
            response = await async_client.get("/api/v1/contributor/owner2/myrepo2/alice.svg")

        assert response.status_code == 200
        assert "Favorite Human" in response.text

    async def test_contributor_badge_doghouse_with_details(self, async_client: AsyncClient) -> None:
        """Doghouse badge with details=true shows shame explanation."""
        from datetime import UTC, datetime

        from github_tamagotchi.services.github import ContributorStats

        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner3", "repo_name": "myrepo3", "name": "Chompy"},
        )

        mock_stats = ContributorStats(
            commits_30d=2,
            last_commit_at=datetime.now(UTC),
            is_top_contributor=False,
            has_failed_ci=True,
            days_since_last_commit=2,
        )

        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=mock_stats,
        ):
            response = await async_client.get(
                "/api/v1/contributor/owner3/myrepo3/bob.svg?details=true"
            )

        assert response.status_code == 200
        assert "Broke CI" in response.text

    async def test_contributor_badge_cache_headers(self, async_client: AsyncClient) -> None:
        """Badge endpoint includes proper cache headers."""
        from github_tamagotchi.services.github import ContributorStats

        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner4", "repo_name": "myrepo4", "name": "Pix"},
        )

        mock_stats = ContributorStats(
            commits_30d=0,
            last_commit_at=None,
            is_top_contributor=False,
            has_failed_ci=False,
            days_since_last_commit=None,
        )

        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_contributor_stats",
            new_callable=AsyncMock,
            return_value=mock_stats,
        ):
            response = await async_client.get("/api/v1/contributor/owner4/myrepo4/eve.svg")

        assert "cache-control" in response.headers
        assert "public" in response.headers["cache-control"]


class TestGenerateShowcaseSvg:
    """Unit tests for the showcase SVG generator."""

    def _make_pet(self, name: str = "Chippy", stage: str = "baby", mood: str = "happy") -> dict:
        return {"name": name, "stage": stage, "mood": mood, "health": 80, "is_dead": False}

    def test_empty_pets_returns_valid_svg(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([], "alice")
        assert svg.strip().startswith("<svg")
        assert "</svg>" in svg

    def test_empty_pets_shows_no_pets_message(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([], "alice")
        assert "No pets yet" in svg
        assert "alice" in svg

    def test_single_pet_shows_name(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet("Fluffy")], "alice")
        assert "Fluffy" in svg

    def test_single_pet_shows_stage_emoji(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet(stage="egg")], "alice")
        assert "🥚" in svg

    def test_dead_pet_shows_tombstone(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        pet = {"name": "Ghost", "stage": "adult", "mood": "content", "health": 0, "is_dead": True}
        svg = generate_showcase_svg([pet], "alice")
        assert "🪦" in svg

    def test_long_name_truncated(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet("A" * 15)], "alice")
        assert "A" * 15 not in svg
        assert "…" in svg

    def test_multiple_pets_all_names_present(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        pets = [self._make_pet("Chippy"), self._make_pet("Fluffy"), self._make_pet("Buddy")]
        svg = generate_showcase_svg(pets, "alice")
        assert "Chippy" in svg
        assert "Fluffy" in svg
        assert "Buddy" in svg

    def test_horizontal_layout_wider_than_vertical(self) -> None:
        import re

        from github_tamagotchi.services.badge import generate_showcase_svg

        pets = [self._make_pet("A"), self._make_pet("B"), self._make_pet("C")]
        svg_h = generate_showcase_svg(pets, "alice", layout="horizontal")
        svg_v = generate_showcase_svg(pets, "alice", layout="vertical")
        w_h = int(re.search(r'width="(\d+)"', svg_h).group(1))  # type: ignore[union-attr]
        w_v = int(re.search(r'width="(\d+)"', svg_v).group(1))  # type: ignore[union-attr]
        assert w_h > w_v

    def test_grid_layout_returns_valid_svg(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        pets = [self._make_pet(f"Pet{i}") for i in range(6)]
        svg = generate_showcase_svg(pets, "alice", layout="grid")
        assert svg.strip().startswith("<svg")
        assert "</svg>" in svg

    def test_light_theme_returns_valid_svg(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet()], "alice", theme="light")
        assert svg.strip().startswith("<svg")
        assert "#f8f9fa" in svg

    def test_dark_theme_default(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet()], "alice")
        assert "#16213e" in svg

    def test_title_includes_username(self) -> None:
        from github_tamagotchi.services.badge import generate_showcase_svg

        svg = generate_showcase_svg([self._make_pet()], "wiebe")
        assert "wiebe" in svg

    def test_unknown_layout_falls_back_to_horizontal(self) -> None:
        import re

        from github_tamagotchi.services.badge import generate_showcase_svg

        pets = [self._make_pet("A"), self._make_pet("B")]
        svg_h = generate_showcase_svg(pets, "u", layout="horizontal")
        svg_u = generate_showcase_svg(pets, "u", layout="unknown")
        w_h = int(re.search(r'width="(\d+)"', svg_h).group(1))  # type: ignore[union-attr]
        w_u = int(re.search(r'width="(\d+)"', svg_u).group(1))  # type: ignore[union-attr]
        assert w_h == w_u


class TestShowcaseEndpoint:
    """Integration tests for the showcase SVG endpoint."""

    async def test_showcase_empty_returns_200(self, async_client: AsyncClient) -> None:
        """Empty showcase returns 200 with an SVG (not 404)."""
        response = await async_client.get("/api/v1/showcase/nobody_with_no_pets.svg")
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]
        body = response.text
        assert body.strip().startswith("<svg")
        assert "No pets yet" in body

    async def test_showcase_with_pets_returns_svg(self, async_client: AsyncClient) -> None:
        """Showcase returns SVG containing pet names for a user with pets."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "showcase_user", "repo_name": "repo1", "name": "Fluffy"},
        )
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "showcase_user", "repo_name": "repo2", "name": "Chippy"},
        )

        response = await async_client.get("/api/v1/showcase/showcase_user.svg")
        assert response.status_code == 200
        body = response.text
        assert "Fluffy" in body
        assert "Chippy" in body

    async def test_showcase_content_type(self, async_client: AsyncClient) -> None:
        """Showcase endpoint returns SVG content type."""
        response = await async_client.get("/api/v1/showcase/anyuser.svg")
        assert "image/svg+xml" in response.headers["content-type"]

    async def test_showcase_cache_headers(self, async_client: AsyncClient) -> None:
        """Showcase endpoint includes proper cache headers."""
        response = await async_client.get("/api/v1/showcase/anyuser.svg")
        assert "cache-control" in response.headers
        assert "public" in response.headers["cache-control"]
        assert "max-age" in response.headers["cache-control"]

    async def test_showcase_layout_horizontal(self, async_client: AsyncClient) -> None:
        """horizontal layout query param is accepted."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "layout_user", "repo_name": "repo", "name": "Pixel"},
        )
        response = await async_client.get("/api/v1/showcase/layout_user.svg?layout=horizontal")
        assert response.status_code == 200

    async def test_showcase_layout_vertical(self, async_client: AsyncClient) -> None:
        """vertical layout query param is accepted."""
        response = await async_client.get("/api/v1/showcase/someuser.svg?layout=vertical")
        assert response.status_code == 200

    async def test_showcase_layout_grid(self, async_client: AsyncClient) -> None:
        """grid layout query param is accepted."""
        response = await async_client.get("/api/v1/showcase/someuser.svg?layout=grid")
        assert response.status_code == 200

    async def test_showcase_invalid_layout_rejected(self, async_client: AsyncClient) -> None:
        """Invalid layout query param returns 422."""
        response = await async_client.get("/api/v1/showcase/someuser.svg?layout=diagonal")
        assert response.status_code == 422

    async def test_showcase_theme_light(self, async_client: AsyncClient) -> None:
        """light theme query param is accepted and changes colours."""
        response = await async_client.get("/api/v1/showcase/someuser.svg?theme=light")
        assert response.status_code == 200

    async def test_showcase_invalid_theme_rejected(self, async_client: AsyncClient) -> None:
        """Invalid theme query param returns 422."""
        response = await async_client.get("/api/v1/showcase/someuser.svg?theme=neon")
        assert response.status_code == 422

    async def test_showcase_max_param_limits_pets(self, async_client: AsyncClient) -> None:
        """max param limits the number of pets shown."""
        for i in range(5):
            await async_client.post(
                "/api/v1/pets",
                json={"repo_owner": "max_user", "repo_name": f"repo{i}", "name": f"Pet{i}"},
            )

        response_limited = await async_client.get("/api/v1/showcase/max_user.svg?max=2")
        response_full = await async_client.get("/api/v1/showcase/max_user.svg?max=10")

        assert response_limited.status_code == 200
        assert response_full.status_code == 200
        import re
        w_limited = int(
            re.search(r'width="(\d+)"', response_limited.text).group(1)  # type: ignore[union-attr]
        )
        w_full = int(
            re.search(r'width="(\d+)"', response_full.text).group(1)  # type: ignore[union-attr]
        )
        assert w_limited < w_full

    async def test_showcase_only_shows_owner_pets(self, async_client: AsyncClient) -> None:
        """Showcase only shows pets belonging to the requested username."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "userA", "repo_name": "repo", "name": "UserAPet"},
        )
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "userB", "repo_name": "repo", "name": "UserBPet"},
        )

        response = await async_client.get("/api/v1/showcase/userA.svg")
        assert response.status_code == 200
        body = response.text
        assert "UserAPet" in body
        assert "UserBPet" not in body
