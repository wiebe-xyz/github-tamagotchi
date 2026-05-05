"""Repository functions for the pet graveyard."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.grave_flower_ip import GraveFlowerIp
from github_tamagotchi.models.pet import Pet


async def get_dead_pets(
    db: AsyncSession, page: int = 1, per_page: int = 20
) -> tuple[list[Pet], int]:
    """Get paginated dead pets, most recent death first. Returns (pets, total_count)."""
    count_q = select(func.count()).select_from(Pet).where(Pet.is_dead.is_(True))
    total = (await db.execute(count_q)).scalar_one()

    q = (
        select(Pet)
        .where(Pet.is_dead.is_(True))
        .order_by(Pet.died_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_dead_pets_by_user(
    db: AsyncSession, username: str, page: int = 1, per_page: int = 20
) -> tuple[list[Pet], int]:
    """Get paginated dead pets for a specific user."""
    base = Pet.is_dead.is_(True) & (Pet.repo_owner == username)
    count_q = select(func.count()).select_from(Pet).where(base)
    total = (await db.execute(count_q)).scalar_one()

    q = (
        select(Pet)
        .where(base)
        .order_by(Pet.died_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_grave(db: AsyncSession, owner: str, repo: str) -> Pet | None:
    """Get a single dead pet by owner/repo. Returns None if not found or not dead."""
    q = select(Pet).where(
        Pet.repo_owner == owner, Pet.repo_name == repo, Pet.is_dead.is_(True)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


def hash_ip(ip: str) -> str:
    """Hash an IP address for privacy-friendly storage."""
    return hashlib.sha256(ip.encode()).hexdigest()


async def add_flower(
    db: AsyncSession, pet_id: int, ip: str
) -> tuple[bool, int]:
    """Add a flower reaction. Returns (was_added, new_count).

    Rate-limited: one flower per IP per grave per 24 hours.
    """
    ip_h = hash_ip(ip)
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    existing = await db.execute(
        select(GraveFlowerIp).where(
            GraveFlowerIp.pet_id == pet_id,
            GraveFlowerIp.ip_hash == ip_h,
        )
    )
    record = existing.scalar_one_or_none()

    if record and record.last_flower_at > cutoff:
        # Already placed today
        pet = await db.get(Pet, pet_id)
        return False, pet.flower_count if pet else 0

    if record:
        record.last_flower_at = datetime.now(UTC)
    else:
        db.add(GraveFlowerIp(pet_id=pet_id, ip_hash=ip_h))

    # Increment flower count
    pet = await db.get(Pet, pet_id)
    if pet:
        pet.flower_count += 1
        await db.commit()
        return True, pet.flower_count

    await db.commit()
    return False, 0


async def update_eulogy(db: AsyncSession, pet_id: int, eulogy: str) -> None:
    """Set the eulogy text on a dead pet."""
    pet = await db.get(Pet, pet_id)
    if pet:
        pet.eulogy = eulogy[:280]
        await db.commit()
