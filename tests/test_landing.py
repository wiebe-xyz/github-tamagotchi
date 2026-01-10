"""Tests for landing page."""

from fastapi.testclient import TestClient

from github_tamagotchi.main import app


def test_landing_page_returns_html():
    """Landing page should return HTML content."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_landing_page_contains_key_elements():
    """Landing page should contain key elements."""
    client = TestClient(app)
    response = client.get("/")
    html = response.text
    assert "GitHub Tamagotchi" in html
    assert "Login with GitHub" in html
    assert "How It Works" in html


def test_static_css_accessible():
    """Static CSS file should be accessible."""
    client = TestClient(app)
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
