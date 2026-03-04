"""Tests for the alerting service."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.models.alert import Alert, AlertStatus, AlertType
from github_tamagotchi.models.pet import Base
from github_tamagotchi.services.alerting import AlertChecker, fire_alert, resolve_alert

# Use SQLite for testing
_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Provide a clean database session for each test."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _session_factory() as session:
        yield session
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _mock_notifications() -> AsyncIterator[None]:
    """Mock notification sending so tests don't make HTTP calls."""
    with (
        patch(
            "github_tamagotchi.services.alerting.send_alert_notification",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "github_tamagotchi.services.alerting.send_resolved_notification",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        yield


class TestFireAlert:
    async def test_creates_new_alert(self, db: AsyncSession) -> None:
        created = await fire_alert(db, AlertType.POLL_FAILED, "Poll failed twice")
        assert created is True

        result = await db.execute(select(Alert))
        alert = result.scalar_one()
        assert alert.alert_type == AlertType.POLL_FAILED.value
        assert alert.status == AlertStatus.FIRING.value
        assert alert.message == "Poll failed twice"

    async def test_deduplicates_active_alerts(self, db: AsyncSession) -> None:
        await fire_alert(db, AlertType.POLL_FAILED, "First")
        created = await fire_alert(db, AlertType.POLL_FAILED, "Second")
        assert created is False

        result = await db.execute(select(Alert))
        alerts = list(result.scalars().all())
        assert len(alerts) == 1

    async def test_different_types_not_deduplicated(self, db: AsyncSession) -> None:
        await fire_alert(db, AlertType.POLL_FAILED, "Poll issue")
        created = await fire_alert(db, AlertType.HIGH_ERROR_RATE, "Error rate high")
        assert created is True

        result = await db.execute(select(Alert))
        alerts = list(result.scalars().all())
        assert len(alerts) == 2


class TestResolveAlert:
    async def test_resolves_active_alert(self, db: AsyncSession) -> None:
        await fire_alert(db, AlertType.POLL_FAILED, "Poll failed")
        resolved = await resolve_alert(db, AlertType.POLL_FAILED)
        assert resolved is True

        result = await db.execute(select(Alert))
        alert = result.scalar_one()
        assert alert.status == AlertStatus.RESOLVED.value
        assert alert.resolved_at is not None

    async def test_resolve_nonexistent_returns_false(self, db: AsyncSession) -> None:
        resolved = await resolve_alert(db, AlertType.POLL_FAILED)
        assert resolved is False

    async def test_can_fire_after_resolve(self, db: AsyncSession) -> None:
        await fire_alert(db, AlertType.POLL_FAILED, "First")
        await resolve_alert(db, AlertType.POLL_FAILED)
        created = await fire_alert(db, AlertType.POLL_FAILED, "Second occurrence")
        assert created is True

        result = await db.execute(
            select(Alert).where(Alert.status == AlertStatus.FIRING.value)
        )
        firing = list(result.scalars().all())
        assert len(firing) == 1
        assert firing[0].message == "Second occurrence"


class TestAlertChecker:
    async def test_poll_failure_fires_at_threshold(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_poll_failures(2)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.POLL_FAILED.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value

    async def test_poll_failure_resolves_on_zero(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_poll_failures(3)
        await db.flush()

        await checker.check_poll_failures(0)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.POLL_FAILED.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.RESOLVED.value

    async def test_poll_failure_below_threshold_no_alert(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_poll_failures(1)
        await db.flush()

        result = await db.execute(select(Alert))
        alerts = list(result.scalars().all())
        assert len(alerts) == 0

    async def test_error_rate_fires_above_threshold(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_error_rate(errors=3, total=10)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.HIGH_ERROR_RATE.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value

    async def test_error_rate_resolves_below_threshold(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_error_rate(errors=3, total=10)
        await db.flush()

        await checker.check_error_rate(errors=0, total=10)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.HIGH_ERROR_RATE.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.RESOLVED.value

    async def test_error_rate_zero_total_no_alert(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_error_rate(errors=0, total=0)
        await db.flush()

        result = await db.execute(select(Alert))
        assert len(list(result.scalars().all())) == 0

    async def test_github_rate_limit_fires(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_github_rate_limit(remaining=50, limit=5000)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.GITHUB_RATE_LIMITED.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value

    async def test_github_rate_limit_resolves(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_github_rate_limit(remaining=10, limit=5000)
        await db.flush()

        await checker.check_github_rate_limit(remaining=4000, limit=5000)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.GITHUB_RATE_LIMITED.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.RESOLVED.value

    async def test_dying_pets_fires(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_dying_pets(dying_count=5, total_count=10)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.MANY_DYING_PETS.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value

    async def test_dying_pets_zero_total_no_alert(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_dying_pets(dying_count=0, total_count=0)
        await db.flush()

        result = await db.execute(select(Alert))
        assert len(list(result.scalars().all())) == 0

    async def test_database_slow_fires(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_database_slow(600.0)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.DATABASE_SLOW.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value

    async def test_database_slow_resolves(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_database_slow(600.0)
        await db.flush()

        await checker.check_database_slow(10.0)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.DATABASE_SLOW.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.RESOLVED.value

    async def test_pet_death_spike_fires(self, db: AsyncSession) -> None:
        checker = AlertChecker(db)
        await checker.check_pet_death_spike(deaths_24h=6)
        await db.flush()

        result = await db.execute(
            select(Alert).where(Alert.alert_type == AlertType.PET_DEATH_SPIKE.value)
        )
        alert = result.scalar_one()
        assert alert.status == AlertStatus.FIRING.value
