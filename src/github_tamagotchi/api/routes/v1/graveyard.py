"""API routes for the pet graveyard."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from github_tamagotchi.api.auth import get_optional_user
from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.repositories import graveyard as graveyard_repo

router = APIRouter(prefix="/api/v1/graveyard", tags=["graveyard"])


class FlowerResponse(BaseModel):
    flower_count: int
    added: bool


class EulogyRequest(BaseModel):
    eulogy: str


class GraveSummary(BaseModel):
    pet_name: str
    repo_owner: str
    repo_name: str
    stage: str
    died_at: str | None
    cause_of_death: str | None
    flower_count: int
    eulogy: str | None

    model_config = {"from_attributes": True}


@router.get("")
async def list_graves(
    session: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
) -> dict[str, object]:
    pets, total = await graveyard_repo.get_dead_pets(session, page, per_page)
    return {
        "graves": [_pet_to_summary(p) for p in pets],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{username}")
async def list_user_graves(
    username: str,
    session: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
) -> dict[str, object]:
    pets, total = await graveyard_repo.get_dead_pets_by_user(
        session, username, page, per_page
    )
    if total == 0:
        raise HTTPException(status_code=404, detail="No graves found for this user")
    return {
        "graves": [_pet_to_summary(p) for p in pets],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{username}/{repo}")
async def get_grave(username: str, repo: str, session: DbSession) -> dict[str, object]:
    pet = await graveyard_repo.get_grave(session, username, repo)
    if not pet:
        raise HTTPException(status_code=404, detail="Grave not found")
    return {
        "grave": _pet_to_summary(pet),
        "created_at": pet.created_at.isoformat() if pet.created_at else None,
        "generation": pet.generation,
        "experience": pet.experience,
        "longest_streak": pet.longest_streak,
    }


@router.post("/{username}/{repo}/flower")
async def add_flower(
    username: str,
    repo: str,
    request: Request,
    session: DbSession,
) -> FlowerResponse:
    pet = await graveyard_repo.get_grave(session, username, repo)
    if not pet:
        raise HTTPException(status_code=404, detail="Grave not found")
    client_ip = request.client.host if request.client else "unknown"
    added, count = await graveyard_repo.add_flower(session, pet.id, client_ip)
    return FlowerResponse(flower_count=count, added=added)


@router.put("/{username}/{repo}/eulogy")
async def set_eulogy(
    username: str,
    repo: str,
    body: EulogyRequest,
    session: DbSession,
    user: Annotated[User | None, Depends(get_optional_user)],
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    pet = await graveyard_repo.get_grave(session, username, repo)
    if not pet:
        raise HTTPException(status_code=404, detail="Grave not found")
    if not pet.user_id or pet.user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the pet owner can set the eulogy"
        )
    if len(body.eulogy) > 280:
        raise HTTPException(
            status_code=400, detail="Eulogy must be 280 characters or less"
        )
    await graveyard_repo.update_eulogy(session, pet.id, body.eulogy)
    return {"eulogy": body.eulogy[:280]}


def _pet_to_summary(pet: Pet) -> dict[str, object]:
    return {
        "pet_name": pet.name,
        "repo_owner": pet.repo_owner,
        "repo_name": pet.repo_name,
        "stage": pet.stage,
        "died_at": pet.died_at.isoformat() if pet.died_at else None,
        "cause_of_death": pet.cause_of_death,
        "flower_count": pet.flower_count,
        "eulogy": pet.eulogy,
    }
