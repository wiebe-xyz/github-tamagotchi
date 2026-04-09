"""Tests for SVG badge generation."""

from httpx import AsyncClient

from github_tamagotchi.services.badge import generate_badge_svg


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
        """Badge includes the emoji sprite for the stage."""
        svg = generate_badge_svg("X", "egg", "content", 100)
        assert "🥚" in svg

        svg = generate_badge_svg("X", "elder", "content", 100)
        assert "🦅" in svg

    def test_contains_mood_sprite(self) -> None:
        """Badge includes the emoji for the mood."""
        svg = generate_badge_svg("X", "adult", "sick", 30)
        assert "🤒" in svg

    def test_health_bar_reflects_value(self) -> None:
        """Health bar width is proportional to health value."""
        svg_full = generate_badge_svg("X", "egg", "content", 100)
        svg_low = generate_badge_svg("X", "egg", "content", 10)
        # Full health: width=80; 10% health: width=8
        assert 'width="80"' in svg_full
        assert 'width="8"' in svg_low

    def test_health_clamped(self) -> None:
        """Health below 0 or above 100 is clamped."""
        svg_over = generate_badge_svg("X", "egg", "content", 200)
        assert 'width="80"' in svg_over  # clamped to 100 → width 80

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
