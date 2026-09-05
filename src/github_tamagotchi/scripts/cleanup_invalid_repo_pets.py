"""One-off cleanup for pets rows with a garbage repo_owner/repo_name.

Background (see issue #245): before ``is_valid_repo_identifier`` was enforced
on every pet-creation path, the badge/profile lazy-create endpoint would
happily persist a placeholder pet for whatever text it was handed — including
unresolved template placeholders (``${ghUrl}``), stray punctuation left over
from parsing a markdown link (``owner/repo)``), and doc-example values
(``owner/repo``, ``*/admin``). Those rows are inert but the 30-minute
``poll_repositories`` job used to hit the GitHub API for them forever. Polling
now skips invalid identifiers on its own (see ``main.py``), and the claim flow
re-validates before promoting a placeholder — this script is only needed to
clear out the pre-existing garbage rows.

What it does:
  * Scans every row in the ``pets`` table.
  * A row failing ``is_valid_repo_identifier(repo_owner, repo_name)`` and with
    ``is_placeholder=True`` is a badge-scan artifact with no user attached —
    safe to delete outright.
  * A row failing validation with ``is_placeholder=False`` (a claimed pet with
    a real ``user_id``) is NEVER deleted automatically — it is printed
    prominently for manual admin review instead. This should be rare to
    nonexistent (the claim flow re-validates as of this fix), but a real
    user's data is never auto-deleted here.

Idempotent: rerunning after a successful apply finds nothing left to delete.

Usage (dry run — the default, makes no changes):
    python -m github_tamagotchi.scripts.cleanup_invalid_repo_pets

Usage (apply the deletions):
    python -m github_tamagotchi.scripts.cleanup_invalid_repo_pets --apply

Run this against the production database as a manual maintenance step (e.g.
via the same shell/job runner used for other one-off maintenance), after
verifying the dry-run output looks sane. It only ever touches
``is_placeholder=True`` rows; anything else is reported, not deleted.
"""

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import select

from github_tamagotchi.core.database import async_session_factory
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.services.naming import is_valid_repo_identifier


@dataclass(frozen=True)
class _PetLike:
    """Minimal shape this module's filtering logic needs from a pet row."""

    id: int
    repo_owner: str
    repo_name: str
    is_placeholder: bool
    user_id: int | None = None


def classify_invalid_pets(
    pets: list[_PetLike],
) -> tuple[list[_PetLike], list[_PetLike]]:
    """Split *pets* into (safe_to_delete, needs_manual_review).

    Only rows that fail ``is_valid_repo_identifier`` are returned at all;
    valid rows are dropped from both lists. Placeholders go in the first
    list (safe to delete — no user owns them); claimed pets go in the
    second (never auto-deleted).
    """
    to_delete: list[_PetLike] = []
    to_review: list[_PetLike] = []
    for pet in pets:
        if is_valid_repo_identifier(pet.repo_owner, pet.repo_name):
            continue
        if pet.is_placeholder:
            to_delete.append(pet)
        else:
            to_review.append(pet)
    return to_delete, to_review


async def _run(apply: bool) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Pet))
        pets = result.scalars().all()

        pet_likes = [
            _PetLike(
                id=p.id,
                repo_owner=p.repo_owner,
                repo_name=p.repo_name,
                is_placeholder=p.is_placeholder,
                user_id=p.user_id,
            )
            for p in pets
        ]
        to_delete, to_review = classify_invalid_pets(pet_likes)

        print(f"Scanned {len(pets)} pets rows.")
        print(f"Invalid placeholder rows (safe to delete): {len(to_delete)}")
        for row in to_delete:
            print(f"  id={row.id} {row.repo_owner}/{row.repo_name}")

        print(f"Invalid CLAIMED rows (NOT deleted — needs manual review): {len(to_review)}")
        for row in to_review:
            print(
                f"  !! REVIEW id={row.id} owner={row.repo_owner!r} "
                f"repo={row.repo_name!r} user_id={row.user_id}"
            )

        if not to_delete:
            print("Nothing to delete.")
            return

        if not apply:
            print(
                f"Dry run: would delete {len(to_delete)} row(s). "
                "Re-run with --apply to actually delete."
            )
            return

        id_by_pet = {p.id: p for p in pets}
        for row in to_delete:
            await session.delete(id_by_pet[row.id])
        await session.commit()
        print(f"Deleted {len(to_delete)} invalid placeholder row(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete invalid placeholder rows (default: dry run only).",
    )
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
