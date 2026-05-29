"""Tests for SEO: robots.txt, sitemap.xml, canonical, meta description, JSON-LD."""

import asyncio

from fastapi.testclient import TestClient

from github_tamagotchi.models.pet import Pet, PetStage
from tests.conftest import test_session_factory


def _add_pet(
    repo_owner: str,
    repo_name: str,
    is_dead: bool = False,
    stage: str = "baby",
) -> None:
    async def _do() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=f"{repo_name}-pet",
                stage=PetStage(stage),
                health=80,
                experience=0,
                is_dead=is_dead,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_do())


class TestRobotsTxt:
    def test_returns_200_and_plain_text(self, client: TestClient) -> None:
        r = client.get("/robots.txt")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]

    def test_disallows_admin_and_auth(self, client: TestClient) -> None:
        r = client.get("/robots.txt")
        assert "Disallow: /admin" in r.text
        assert "Disallow: /auth/" in r.text
        assert "Disallow: /dashboard" in r.text
        assert "Disallow: /register" in r.text

    def test_points_to_sitemap(self, client: TestClient) -> None:
        r = client.get("/robots.txt")
        assert "Sitemap:" in r.text
        assert "/sitemap.xml" in r.text


class TestSitemapXml:
    def test_returns_xml(self, client: TestClient) -> None:
        r = client.get("/sitemap.xml")
        assert r.status_code == 200
        assert "application/xml" in r.headers["content-type"]
        assert r.text.startswith("<?xml")
        assert "<urlset" in r.text

    def test_includes_landing_and_static_routes(self, client: TestClient) -> None:
        r = client.get("/sitemap.xml")
        assert "/leaderboard" in r.text
        assert "/graveyard" in r.text

    def test_includes_living_and_dead_pet_urls(self, client: TestClient) -> None:
        _add_pet("alice", "alive-repo", is_dead=False, stage="baby")
        _add_pet("bob", "dead-repo", is_dead=True, stage="egg")
        r = client.get("/sitemap.xml")
        assert "/pet/alice/alive-repo" in r.text
        assert "/pet/alice/alive-repo/insights" in r.text
        assert "/graveyard/bob/dead-repo" in r.text
        # Org page for owner of a living pet should appear too
        assert "/org/alice" in r.text


class TestSeoMetaOnPublicPages:
    def test_landing_has_canonical_and_description(self, client: TestClient) -> None:
        r = client.get("/")
        assert '<link rel="canonical"' in r.text
        assert '<meta name="description"' in r.text
        assert 'application/ld+json' in r.text

    def test_leaderboard_has_canonical(self, client: TestClient) -> None:
        r = client.get("/leaderboard")
        assert '<link rel="canonical"' in r.text
        assert '/leaderboard' in r.text

    def test_graveyard_has_canonical(self, client: TestClient) -> None:
        r = client.get("/graveyard")
        assert '<link rel="canonical"' in r.text

    def test_pet_profile_has_canonical_and_jsonld(self, client: TestClient) -> None:
        _add_pet("charlie", "seo-test-repo", is_dead=False, stage="child")
        r = client.get("/pet/charlie/seo-test-repo")
        assert r.status_code == 200
        assert '<link rel="canonical"' in r.text
        assert "BreadcrumbList" in r.text


class TestNoIndexOnPrivatePages:
    def test_dashboard_redirects_or_noindex(self, client: TestClient) -> None:
        # /dashboard requires auth and typically redirects; just verify it's not
        # an indexable success page.
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code in (200, 302, 303, 307, 401, 403)
        if r.status_code == 200:
            assert "noindex" in r.text
