"""Shared pytest fixtures for all tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from github_tamagotchi.main import app
from github_tamagotchi.services.github import RepoHealth


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def healthy_repo() -> RepoHealth:
    """Create a healthy repository state."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(hours=1),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=True,
        has_stale_dependencies=False,
    )


@pytest.fixture
def unhealthy_repo() -> RepoHealth:
    """Create an unhealthy repository state."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(days=10),
        open_prs_count=5,
        oldest_pr_age_hours=100,
        open_issues_count=20,
        oldest_issue_age_days=30,
        last_ci_success=False,
        has_stale_dependencies=True,
    )


@pytest.fixture
def mock_commit_response() -> list[dict[str, Any]]:
    """Mock GitHub commits API response."""
    return [
        {
            "sha": "abc123",
            "commit": {
                "committer": {
                    "date": "2025-01-10T12:00:00Z"
                }
            }
        }
    ]


@pytest.fixture
def mock_prs_response() -> list[dict[str, Any]]:
    """Mock GitHub pull requests API response."""
    return [
        {
            "id": 1,
            "number": 1,
            "title": "Test PR",
            "created_at": "2025-01-08T12:00:00Z",
            "state": "open",
        },
        {
            "id": 2,
            "number": 2,
            "title": "Another PR",
            "created_at": "2025-01-09T12:00:00Z",
            "state": "open",
        },
    ]


@pytest.fixture
def mock_issues_response() -> list[dict[str, Any]]:
    """Mock GitHub issues API response."""
    return [
        {
            "id": 1,
            "number": 1,
            "title": "Bug report",
            "created_at": "2025-01-05T12:00:00Z",
            "state": "open",
        },
        {
            "id": 2,
            "number": 2,
            "title": "Feature request",
            "created_at": "2025-01-07T12:00:00Z",
            "state": "open",
        },
        {
            "id": 3,
            "number": 3,
            "title": "PR as issue",
            "created_at": "2025-01-09T12:00:00Z",
            "state": "open",
            "pull_request": {"url": "https://..."},  # Should be filtered out
        },
    ]


@pytest.fixture
def mock_repo_response() -> dict[str, Any]:
    """Mock GitHub repository API response."""
    return {
        "id": 12345,
        "name": "test-repo",
        "full_name": "owner/test-repo",
        "default_branch": "main",
    }


@pytest.fixture
def mock_status_response_success() -> dict[str, Any]:
    """Mock GitHub status API response for successful CI."""
    return {
        "state": "success",
        "statuses": [],
    }


@pytest.fixture
def mock_status_response_failure() -> dict[str, Any]:
    """Mock GitHub status API response for failed CI."""
    return {
        "state": "failure",
        "statuses": [],
    }
