"""E2E: Pet evolution through stages via accumulated experience."""

import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.pet_logic import (
    EVOLUTION_THRESHOLDS,
    calculate_experience,
    get_next_stage,
)

from .conftest import mock_github_repo


@pytest.mark.asyncio
class TestEvolution:
    """Pet evolves through stages as experience accumulates."""

    async def test_egg_evolves_to_baby_at_threshold(
        self, e2e_db: AsyncSession
    ) -> None:
        """Pet evolves from egg to baby when experience reaches 100."""
        pet = Pet(
            repo_owner="owner",
            repo_name="evolve-test",
            name="EggPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=100,
            experience=99,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        # Still egg at 99
        assert get_next_stage(PetStage.EGG, 99) == PetStage.EGG

        # Evolves at 100
        pet.experience = 100
        new_stage = get_next_stage(PetStage.EGG, pet.experience)
        pet.stage = new_stage.value
        await e2e_db.commit()
        await e2e_db.refresh(pet)
        assert pet.stage == PetStage.BABY.value

    async def test_full_evolution_chain(self, e2e_db: AsyncSession) -> None:
        """Pet can evolve through all stages with sufficient experience."""
        pet = Pet(
            repo_owner="owner",
            repo_name="full-evolve",
            name="FullPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=100,
            experience=0,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        expected_stages = [
            (100, PetStage.BABY),
            (500, PetStage.CHILD),
            (1500, PetStage.TEEN),
            (5000, PetStage.ADULT),
            (15000, PetStage.ELDER),
        ]

        for exp, expected_stage in expected_stages:
            pet.experience = exp
            new_stage = get_next_stage(PetStage(pet.stage), pet.experience)
            assert new_stage == expected_stage, (
                f"At exp={exp}, expected {expected_stage} got {new_stage}"
            )
            pet.stage = new_stage.value

        await e2e_db.commit()
        await e2e_db.refresh(pet)
        assert pet.stage == PetStage.ELDER.value
        assert pet.experience == 15000

    async def test_elder_does_not_evolve_further(
        self, e2e_db: AsyncSession
    ) -> None:
        """Elder is the max stage — no further evolution."""
        pet = Pet(
            repo_owner="owner",
            repo_name="elder-test",
            name="ElderPet",
            stage=PetStage.ELDER.value,
            mood=PetMood.HAPPY.value,
            health=100,
            experience=99999,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        new_stage = get_next_stage(PetStage.ELDER, pet.experience)
        assert new_stage == PetStage.ELDER

    @respx.mock
    async def test_evolution_via_polling_cycles(
        self, e2e_db: AsyncSession
    ) -> None:
        """Pet evolves from egg to baby after enough healthy poll cycles."""
        pet = Pet(
            repo_owner="owner",
            repo_name="poll-evolve",
            name="PollPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=100,
            experience=0,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        mock_github_repo("owner", "poll-evolve")
        service = GitHubService(token="fake-token")

        # Each healthy poll gives 30 exp (CI success=10 + recent commit=20)
        # Need 100 exp → ceil(100/30) = 4 cycles
        cycles = 0
        while PetStage(pet.stage) == PetStage.EGG and cycles < 10:
            health = await service.get_repo_health("owner", "poll-evolve")
            exp = calculate_experience(health)
            pet.experience += exp
            pet.stage = get_next_stage(PetStage(pet.stage), pet.experience).value
            cycles += 1

        await e2e_db.commit()
        await e2e_db.refresh(pet)

        assert pet.stage == PetStage.BABY.value
        assert pet.experience >= EVOLUTION_THRESHOLDS[PetStage.BABY]
        assert cycles == 4  # 4 × 30 = 120 ≥ 100

    async def test_evolution_thresholds_are_monotonic(self) -> None:
        """Evolution thresholds increase with each stage."""
        stages = list(PetStage)
        thresholds = [EVOLUTION_THRESHOLDS[s] for s in stages]
        for i in range(1, len(thresholds)):
            assert thresholds[i] > thresholds[i - 1]

    async def test_high_xp_does_not_skip_stages(self) -> None:
        """get_next_stage only advances one stage even with XP far beyond threshold."""
        # EGG with enough XP for CHILD (500) should still only go to BABY
        result = get_next_stage(PetStage.EGG, 500)
        assert result == PetStage.BABY

        # BABY with enough XP for ADULT (5000) should still only go to CHILD
        result = get_next_stage(PetStage.BABY, 5000)
        assert result == PetStage.CHILD
