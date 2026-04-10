"""Tests for pet skin unlock and selection functionality."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet, PetSkin, PetStage
from github_tamagotchi.services.pet_logic import SKIN_UNLOCK_CONDITIONS, get_unlocked_skins


class TestPetSkinEnum:
    """Tests for the PetSkin enum."""

    def test_all_skins_defined(self) -> None:
        """All expected skins should be defined."""
        expected = {"classic", "robot", "dragon", "ghost"}
        actual = {s.value for s in PetSkin}
        assert actual == expected

    def test_skins_are_lowercase_strings(self) -> None:
        """Skin values should be lowercase strings."""
        for skin in PetSkin:
            assert isinstance(skin.value, str)
            assert skin.value.islower()

    def test_classic_is_default(self) -> None:
        """Classic skin should always be in enum."""
        assert PetSkin.CLASSIC == "classic"


class TestGetUnlockedSkins:
    """Tests for the get_unlocked_skins logic."""

    def _make_pet(
        self,
        stage: str = PetStage.EGG,
        low_health_recoveries: int = 0,
    ) -> Pet:
        pet = Pet()
        pet.stage = stage
        pet.low_health_recoveries = low_health_recoveries
        return pet

    def test_classic_always_unlocked(self) -> None:
        """Classic skin is unlocked regardless of stage."""
        pet = self._make_pet(stage=PetStage.EGG)
        assert PetSkin.CLASSIC in get_unlocked_skins(pet)

    def test_robot_locked_before_adult(self) -> None:
        """Robot skin is NOT unlocked below Adult stage."""
        for stage in (PetStage.EGG, PetStage.BABY, PetStage.CHILD, PetStage.TEEN):
            pet = self._make_pet(stage=stage)
            # Robot should be locked below Adult
            assert PetSkin.ROBOT not in get_unlocked_skins(pet), stage

    def test_robot_unlocked_at_adult(self) -> None:
        """Robot skin is unlocked at Adult stage."""
        pet = self._make_pet(stage=PetStage.ADULT)
        assert PetSkin.ROBOT in get_unlocked_skins(pet)

    def test_robot_unlocked_at_elder(self) -> None:
        """Robot skin remains unlocked at Elder stage."""
        pet = self._make_pet(stage=PetStage.ELDER)
        assert PetSkin.ROBOT in get_unlocked_skins(pet)

    def test_dragon_locked_before_elder(self) -> None:
        """Dragon skin is NOT unlocked below Elder stage."""
        for stage in (PetStage.EGG, PetStage.BABY, PetStage.CHILD, PetStage.TEEN, PetStage.ADULT):
            pet = self._make_pet(stage=stage)
            # Dragon should be locked below Elder
            assert PetSkin.DRAGON not in get_unlocked_skins(pet), stage

    def test_dragon_unlocked_at_elder(self) -> None:
        """Dragon skin is unlocked at Elder stage."""
        pet = self._make_pet(stage=PetStage.ELDER)
        assert PetSkin.DRAGON in get_unlocked_skins(pet)

    def test_ghost_locked_below_three_recoveries(self) -> None:
        """Ghost skin requires exactly 3 low-health recoveries."""
        for count in (0, 1, 2):
            pet = self._make_pet(low_health_recoveries=count)
            # Ghost should be locked below 3 recoveries
            assert PetSkin.GHOST not in get_unlocked_skins(pet), count

    def test_ghost_unlocked_at_three_recoveries(self) -> None:
        """Ghost skin is unlocked at 3 low-health recoveries."""
        pet = self._make_pet(low_health_recoveries=3)
        assert PetSkin.GHOST in get_unlocked_skins(pet)

    def test_ghost_unlocked_above_three_recoveries(self) -> None:
        """Ghost skin stays unlocked above 3 recoveries."""
        pet = self._make_pet(low_health_recoveries=10)
        assert PetSkin.GHOST in get_unlocked_skins(pet)

    def test_elder_pet_with_recoveries_unlocks_all(self) -> None:
        """Elder pet with 3 recoveries has all skins unlocked."""
        pet = self._make_pet(stage=PetStage.ELDER, low_health_recoveries=3)
        unlocked = get_unlocked_skins(pet)
        for skin in PetSkin:
            assert skin in unlocked, f"{skin} should be unlocked"

    def test_unlock_conditions_cover_all_skins(self) -> None:
        """Every skin should have an unlock condition description."""
        for skin in PetSkin:
            assert skin in SKIN_UNLOCK_CONDITIONS
            assert SKIN_UNLOCK_CONDITIONS[skin]


class TestSelectSkinCrud:
    """Tests for the select_skin CRUD operation."""

    async def test_select_valid_skin(self, test_db: AsyncSession) -> None:
        """select_skin should update the skin field."""
        pet = await pet_crud.create_pet(test_db, "owner", "repo", "Fluffy")
        updated = await pet_crud.select_skin(test_db, pet, PetSkin.CLASSIC)
        assert updated.skin == PetSkin.CLASSIC.value

    async def test_skin_default_is_classic(self, test_db: AsyncSession) -> None:
        """Newly created pet should default to classic skin."""
        pet = await pet_crud.create_pet(test_db, "owner", "repo", "Fluffy")
        assert pet.skin == PetSkin.CLASSIC.value


class TestSkinApiEndpoints:
    """Tests for skin-related API endpoints."""

    async def test_list_skins_returns_all_skins(self, async_client: AsyncClient) -> None:
        """GET /pets/{owner}/{repo}/skins returns all skins."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.get("/api/v1/pets/owner/repo/skins")
        assert response.status_code == 200
        data = response.json()
        skin_values = {item["skin"] for item in data}
        assert skin_values == {s.value for s in PetSkin}

    async def test_list_skins_classic_always_unlocked(self, async_client: AsyncClient) -> None:
        """Classic skin is always unlocked."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.get("/api/v1/pets/owner/repo/skins")
        data = response.json()
        classic = next(item for item in data if item["skin"] == "classic")
        assert classic["unlocked"] is True

    async def test_list_skins_robot_locked_for_egg(self, async_client: AsyncClient) -> None:
        """Robot skin is locked for a new egg-stage pet."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.get("/api/v1/pets/owner/repo/skins")
        data = response.json()
        robot = next(item for item in data if item["skin"] == "robot")
        assert robot["unlocked"] is False

    async def test_list_skins_not_found(self, async_client: AsyncClient) -> None:
        """GET skins for missing pet returns 404."""
        response = await async_client.get("/api/v1/pets/nobody/norepo/skins")
        assert response.status_code == 404

    async def test_select_classic_skin_succeeds(self, async_client: AsyncClient) -> None:
        """PUT skin with classic (always unlocked) succeeds."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.put(
            "/api/v1/pets/owner/repo/skin",
            json={"skin": "classic"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pet"]["skin"] == "classic"
        assert "classic" in data["message"]

    async def test_select_locked_skin_returns_403(self, async_client: AsyncClient) -> None:
        """PUT skin with locked skin returns 403."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.put(
            "/api/v1/pets/owner/repo/skin",
            json={"skin": "dragon"},
        )
        assert response.status_code == 403

    async def test_select_unknown_skin_returns_400(self, async_client: AsyncClient) -> None:
        """PUT skin with invalid skin name returns 400."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        response = await async_client.put(
            "/api/v1/pets/owner/repo/skin",
            json={"skin": "unicorn"},
        )
        assert response.status_code == 400

    async def test_select_skin_not_found_returns_404(self, async_client: AsyncClient) -> None:
        """PUT skin for missing pet returns 404."""
        response = await async_client.put(
            "/api/v1/pets/nobody/norepo/skin",
            json={"skin": "classic"},
        )
        assert response.status_code == 404

    async def test_pet_response_includes_skin_fields(self, async_client: AsyncClient) -> None:
        """Pet response includes skin and low_health_recoveries."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Fluffy"},
        )
        data = response.json()
        assert "skin" in data
        assert data["skin"] == "classic"
        assert "low_health_recoveries" in data
        assert data["low_health_recoveries"] == 0
