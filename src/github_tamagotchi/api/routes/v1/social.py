"""Social endpoints: leaderboard, showcase SVG, contributor badge SVG."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from fastapi.responses import Response

from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.schemas.social import (
    LeaderboardCategory,
    LeaderboardEntry,
    LeaderboardResponse,
)
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.badge import ContributorStanding, classify_contributor_standing
from github_tamagotchi.services.github import GitHubService

router: APIRouter = APIRouter(prefix="/api/v1", tags=["social"])

# Shared headers for all SVG responses
_SVG_HEADERS = {
    "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
    "Content-Type": "image/svg+xml; charset=utf-8",
}

_LEADERBOARD_CATEGORIES = [
    {
        "id": "most_experienced",
        "title": "Most Experienced",
        "description": "Highest total XP earned",
        "value_field": "experience",
    },
    {
        "id": "longest_streak",
        "title": "Longest Streak",
        "description": "Most consecutive days with commits",
        "value_field": "longest_streak",
    },
]


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(session: DbSession) -> LeaderboardResponse:
    """Return the public leaderboard with multiple categories."""
    categories: list[LeaderboardCategory] = []
    now = datetime.now(UTC)

    for cat in _LEADERBOARD_CATEGORIES:
        pets = await pet_service.get_leaderboard(session, cat["id"], limit=10)
        entries = [
            LeaderboardEntry(
                rank=i + 1,
                pet_name=p.name,
                repo_owner=p.repo_owner,
                repo_name=p.repo_name,
                stage=p.stage,
                value=getattr(p, cat["value_field"]),
            )
            for i, p in enumerate(pets)
        ]
        categories.append(
            LeaderboardCategory(
                id=cat["id"],
                title=cat["title"],
                description=cat["description"],
                entries=entries,
            )
        )

    return LeaderboardResponse(categories=categories, cached_at=now)


@router.get("/showcase/{username}.svg", response_class=Response)
async def get_showcase(
    username: str,
    session: DbSession,
    layout: str = Query(default="horizontal", pattern="^(horizontal|vertical|grid)$"),
    theme: str = Query(default="dark", pattern="^(light|dark)$"),
    max: int = Query(default=10, ge=1, le=50),
) -> Response:
    """Return an SVG showcase of all pets for a GitHub user."""
    from github_tamagotchi.services.badge import generate_showcase_svg

    pets = await pet_service.get_by_username(session, username, limit=max)
    pets_data = [
        {
            "name": pet.name,
            "stage": pet.stage,
            "mood": pet.mood,
            "health": pet.health,
            "is_dead": pet.is_dead,
        }
        for pet in pets
    ]
    svg_content = generate_showcase_svg(pets_data, username, layout=layout, theme=theme)
    return Response(content=svg_content, media_type="image/svg+xml", headers=_SVG_HEADERS)


@router.get("/contributor/{repo_owner}/{repo_name}/{username}.svg", response_class=Response)
async def get_contributor_badge(
    repo_owner: str,
    repo_name: str,
    username: str,
    session: DbSession,
    details: bool = Query(default=False, description="Include shame detail in badge"),
) -> Response:
    """Return an SVG badge showing a contributor's standing with the repo pet."""
    from github_tamagotchi.services.badge import generate_contributor_badge_svg
    from github_tamagotchi.services.github import ContributorStats

    pet = await get_pet_or_404(repo_owner, repo_name, session)

    gh = GitHubService()
    try:
        stats: ContributorStats = await gh.get_contributor_stats(repo_owner, repo_name, username)
    except Exception:
        stats = ContributorStats(
            commits_30d=0,
            last_commit_at=None,
            is_top_contributor=False,
            has_failed_ci=False,
            days_since_last_commit=None,
        )

    standing = classify_contributor_standing(
        commits_30d=stats.commits_30d,
        is_top_contributor=stats.is_top_contributor,
        has_failed_ci=stats.has_failed_ci,
        days_since_last_commit=stats.days_since_last_commit,
    )

    shame_detail: str | None = None
    if details and standing == ContributorStanding.DOGHOUSE:
        days = stats.days_since_last_commit or 0
        shame_detail = f"Broke CI {days}d ago" if days else "Broke CI recently"

    svg_content = generate_contributor_badge_svg(
        pet_name=pet.name,
        pet_stage=pet.stage,
        username=username,
        standing=standing,
        score=stats.commits_30d * 10 if standing == ContributorStanding.GOOD else None,
        days_away=stats.days_since_last_commit if standing == ContributorStanding.ABSENT else None,
        shame_detail=shame_detail,
    )
    return Response(content=svg_content, media_type="image/svg+xml", headers=_SVG_HEADERS)
