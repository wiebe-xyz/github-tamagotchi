"""Tests for the invalid-repo-identifier pets cleanup script.

Exercises only the pure filtering logic (``classify_invalid_pets``) against
in-memory fake rows — no live database involved. See the script's own
docstring for how to run it against a real database.
"""

from github_tamagotchi.scripts.cleanup_invalid_repo_pets import (
    _PetLike,
    classify_invalid_pets,
)


def test_valid_rows_are_ignored() -> None:
    pets = [
        _PetLike(id=1, repo_owner="octocat", repo_name="hello-world", is_placeholder=True),
        _PetLike(
            id=2,
            repo_owner="octocat",
            repo_name="hello-world",
            is_placeholder=False,
            user_id=42,
        ),
    ]
    to_delete, to_review = classify_invalid_pets(pets)
    assert to_delete == []
    assert to_review == []


def test_invalid_placeholder_rows_are_marked_for_deletion() -> None:
    pets = [
        _PetLike(id=1, repo_owner="owner", repo_name="repo)", is_placeholder=True),
        _PetLike(id=2, repo_owner="xyzhou120", repo_name="${ghUrl}", is_placeholder=True),
        _PetLike(id=3, repo_owner="*", repo_name="admin", is_placeholder=True),
    ]
    to_delete, to_review = classify_invalid_pets(pets)
    assert {p.id for p in to_delete} == {1, 2, 3}
    assert to_review == []


def test_invalid_claimed_rows_are_reported_not_deleted() -> None:
    """A claimed pet (real user_id) with a bad identifier is never auto-deleted."""
    pets = [
        _PetLike(
            id=9,
            repo_owner="owner",
            repo_name="repo)",
            is_placeholder=False,
            user_id=7,
        ),
    ]
    to_delete, to_review = classify_invalid_pets(pets)
    assert to_delete == []
    assert [p.id for p in to_review] == [9]


def test_mixed_rows_are_split_correctly() -> None:
    pets = [
        _PetLike(id=1, repo_owner="octocat", repo_name="hello-world", is_placeholder=True),
        _PetLike(id=2, repo_owner="owner", repo_name="repo)", is_placeholder=True),
        _PetLike(
            id=3,
            repo_owner="owner",
            repo_name="repo)",
            is_placeholder=False,
            user_id=1,
        ),
        _PetLike(
            id=4,
            repo_owner="octocat",
            repo_name="spoon-knife",
            is_placeholder=False,
            user_id=2,
        ),
    ]
    to_delete, to_review = classify_invalid_pets(pets)
    assert [p.id for p in to_delete] == [2]
    assert [p.id for p in to_review] == [3]
