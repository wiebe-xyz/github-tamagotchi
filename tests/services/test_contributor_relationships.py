"""Tests for contributor relationship score and standing logic."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.models.contributor_relationship import ContributorStanding
from github_tamagotchi.services.contributor_relationships import (
    ContributorUpdate,
    build_contributor_updates,
    calculate_score,
    calculate_standing,
)
from github_tamagotchi.services.github import AllContributorActivity


class TestCalculateScore:
    def test_empty(self) -> None:
        assert calculate_score(0, 0) == 0

    def test_commits_only(self) -> None:
        assert calculate_score(3, 0) == 15  # 3 * 5

    def test_merged_prs_only(self) -> None:
        assert calculate_score(0, 2) == 20  # 2 * 10

    def test_both(self) -> None:
        assert calculate_score(4, 1) == 30  # 4*5 + 1*10


class TestCalculateStanding:
    def _now(self) -> datetime:
        return datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)

    def test_absent_when_no_activity(self) -> None:
        now = self._now()
        assert calculate_standing(100, False, None, now) == ContributorStanding.ABSENT

    def test_absent_when_stale(self) -> None:
        now = self._now()
        last = now - timedelta(days=31)
        assert calculate_standing(50, False, last, now) == ContributorStanding.ABSENT

    def test_doghouse_when_negative_score(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        assert calculate_standing(-5, False, last, now) == ContributorStanding.DOGHOUSE

    def test_favorite_when_top_scorer(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        assert calculate_standing(80, True, last, now) == ContributorStanding.FAVORITE

    def test_good_when_score_above_threshold(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        assert calculate_standing(51, False, last, now) == ContributorStanding.GOOD

    def test_neutral_when_score_below_threshold(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        assert calculate_standing(30, False, last, now) == ContributorStanding.NEUTRAL

    def test_neutral_at_zero_score(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        assert calculate_standing(0, False, last, now) == ContributorStanding.NEUTRAL

    def test_good_at_threshold_boundary(self) -> None:
        now = self._now()
        last = now - timedelta(days=1)
        # score > 50 is good, exactly 50 is neutral
        assert calculate_standing(50, False, last, now) == ContributorStanding.NEUTRAL
        assert calculate_standing(51, False, last, now) == ContributorStanding.GOOD


class TestBuildContributorUpdates:
    def _now(self) -> datetime:
        return datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)

    def _recent(self) -> datetime:
        return self._now() - timedelta(days=1)

    def test_empty_activity(self) -> None:
        activity = AllContributorActivity(
            commits_by_user={},
            merged_prs_by_user={},
            last_activity_by_user={},
        )
        updates = build_contributor_updates(activity, self._now())
        assert updates == []

    def test_single_contributor(self) -> None:
        activity = AllContributorActivity(
            commits_by_user={"alice": 3},
            merged_prs_by_user={},
            last_activity_by_user={"alice": self._recent()},
        )
        updates = build_contributor_updates(activity, self._now())
        assert len(updates) == 1
        alice = updates[0]
        assert isinstance(alice, ContributorUpdate)
        assert alice.github_username == "alice"
        assert alice.score == 15  # 3 * 5
        # As the sole contributor, alice is the top scorer → favorite
        assert alice.standing == ContributorStanding.FAVORITE
        assert "3 commits" in alice.good_deeds[0]

    def test_favorite_is_top_scorer(self) -> None:
        activity = AllContributorActivity(
            commits_by_user={"alice": 20, "bob": 2},
            merged_prs_by_user={},
            last_activity_by_user={"alice": self._recent(), "bob": self._recent()},
        )
        updates = build_contributor_updates(activity, self._now())
        by_user = {u.github_username: u for u in updates}
        # alice has 100 pts (top scorer, and >50)
        assert by_user["alice"].standing == ContributorStanding.FAVORITE
        # bob has 10 pts → neutral
        assert by_user["bob"].standing == ContributorStanding.NEUTRAL

    def test_absent_contributor_not_in_list(self) -> None:
        """Contributors with no activity data in last 30 days are absent."""
        old = self._now() - timedelta(days=35)
        activity = AllContributorActivity(
            commits_by_user={"alice": 0},
            merged_prs_by_user={},
            last_activity_by_user={"alice": old},
        )
        # alice is in commits_by_user but with 0 commits, so no entry
        # (AllContributorActivity only holds non-zero counts, but let's test explicit)
        updates = build_contributor_updates(activity, self._now())
        # alice has 0 score but is in the activity keys from commits_by_user
        # She will appear but be marked absent due to stale last_activity
        by_user = {u.github_username: u for u in updates}
        assert by_user["alice"].standing == ContributorStanding.ABSENT

    def test_merged_prs_add_good_deeds(self) -> None:
        activity = AllContributorActivity(
            commits_by_user={},
            merged_prs_by_user={"bob": 2},
            last_activity_by_user={"bob": self._recent()},
        )
        updates = build_contributor_updates(activity, self._now())
        bob = updates[0]
        assert bob.score == 20  # 2 * 10
        assert any("PR" in deed for deed in bob.good_deeds)

    def test_no_favorite_when_all_zero_score(self) -> None:
        """When max score is 0, no one gets favorite standing."""
        activity = AllContributorActivity(
            commits_by_user={"alice": 0},
            merged_prs_by_user={},
            last_activity_by_user={"alice": self._recent()},
        )
        updates = build_contributor_updates(activity, self._now())
        assert updates[0].standing == ContributorStanding.NEUTRAL
