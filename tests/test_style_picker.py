"""Tests for the style picker feature."""

from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from github_tamagotchi.services.image_generation import (
    DEFAULT_STYLE,
    STAGE_PROMPTS,
    STYLES,
    build_prompt,
    get_pet_appearance,
)


class TestStyles:
    """Tests for the STYLES dictionary and build_prompt."""

    def test_all_expected_styles_defined(self) -> None:
        """All 5 expected styles should be present."""
        expected = {"kawaii", "doom_metal", "wizard", "retro_scifi", "minimalist"}
        assert set(STYLES.keys()) == expected

    def test_each_style_has_required_keys(self) -> None:
        """Each style entry must have label, description, prompt_prefix, and negative."""
        required_keys = {"label", "description", "prompt_prefix", "negative"}
        for style_id, style_def in STYLES.items():
            missing = required_keys - style_def.keys()
            assert not missing, f"Style '{style_id}' missing keys: {missing}"

    def test_default_style_is_kawaii(self) -> None:
        """DEFAULT_STYLE should be 'kawaii'."""
        assert DEFAULT_STYLE == "kawaii"

    def test_build_prompt_default_style(self) -> None:
        """build_prompt without explicit style uses kawaii."""
        appearance = get_pet_appearance("owner", "repo")
        prompt = build_prompt(appearance, "egg")
        kawaii_prefix = STYLES["kawaii"]["prompt_prefix"]
        assert kawaii_prefix in prompt

    def test_build_prompt_different_styles_produce_different_prompts(self) -> None:
        """Different styles should produce different prompts."""
        appearance = get_pet_appearance("owner", "repo")
        prompts = {
            style_id: build_prompt(appearance, "adult", style=style_id)
            for style_id in STYLES
        }
        # All prompts should be unique
        assert len(set(prompts.values())) == len(STYLES)

    def test_build_prompt_uses_style_prefix(self) -> None:
        """build_prompt should embed the style's prompt_prefix."""
        appearance = get_pet_appearance("testowner", "testrepo")
        for style_id, style_def in STYLES.items():
            prompt = build_prompt(appearance, "adult", style=style_id)
            assert style_def["prompt_prefix"] in prompt, (
                f"Style '{style_id}' prefix not found in prompt"
            )

    def test_build_prompt_unknown_style_falls_back_to_default(self) -> None:
        """Unknown style key should fall back to the default (kawaii) style."""
        appearance = get_pet_appearance("owner", "repo")
        prompt = build_prompt(appearance, "adult", style="nonexistent_style")
        kawaii_prefix = STYLES[DEFAULT_STYLE]["prompt_prefix"]
        assert kawaii_prefix in prompt

    def test_build_prompt_includes_stage_description(self) -> None:
        """Stage description should appear in the prompt."""
        from github_tamagotchi.models.pet import PetStage

        appearance = get_pet_appearance("owner", "repo")
        for stage in PetStage:
            prompt = build_prompt(appearance, stage.value)
            assert STAGE_PROMPTS[stage.value] in prompt


class TestStylesEndpoint:
    """Tests for GET /api/v1/styles."""

    async def test_returns_all_five_styles(self, async_client: AsyncClient) -> None:
        """GET /api/v1/styles should return all 5 style definitions."""
        response = await async_client.get("/api/v1/styles")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    async def test_each_style_has_id_label_description(self, async_client: AsyncClient) -> None:
        """Each style in the response should have id, label, description."""
        response = await async_client.get("/api/v1/styles")
        assert response.status_code == 200
        for style in response.json():
            assert "id" in style
            assert "label" in style
            assert "description" in style

    async def test_style_ids_match_keys(self, async_client: AsyncClient) -> None:
        """The style ids in the response should match STYLES.keys()."""
        response = await async_client.get("/api/v1/styles")
        assert response.status_code == 200
        returned_ids = {s["id"] for s in response.json()}
        assert returned_ids == set(STYLES.keys())


class TestCreatePetWithStyle:
    """Tests for POST /api/v1/pets with style field."""

    async def test_create_pet_default_style(self, async_client: AsyncClient) -> None:
        """Creating a pet without style uses the default (kawaii)."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner1", "repo_name": "repo1", "name": "MyPet"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["style"] == DEFAULT_STYLE

    async def test_create_pet_with_valid_style(self, async_client: AsyncClient) -> None:
        """Creating a pet with a valid style stores it correctly."""
        response = await async_client.post(
            "/api/v1/pets",
            json={
                "repo_owner": "owner2",
                "repo_name": "repo2",
                "name": "DarkPet",
                "style": "doom_metal",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["style"] == "doom_metal"

    async def test_create_pet_with_invalid_style_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        """Creating a pet with an invalid style should return 422."""
        response = await async_client.post(
            "/api/v1/pets",
            json={
                "repo_owner": "owner3",
                "repo_name": "repo3",
                "name": "BadPet",
                "style": "invalid_style",
            },
        )
        assert response.status_code == 422

    async def test_create_pet_all_valid_styles(self, async_client: AsyncClient) -> None:
        """Each valid style can be used to create a pet."""
        for i, style_id in enumerate(STYLES.keys()):
            response = await async_client.post(
                "/api/v1/pets",
                json={
                    "repo_owner": f"styleowner{i}",
                    "repo_name": f"stylerepo{i}",
                    "name": f"StylePet{i}",
                    "style": style_id,
                },
            )
            assert response.status_code == 201, f"Failed for style '{style_id}'"
            assert response.json()["style"] == style_id


class TestUpdatePetStyle:
    """Tests for PUT /api/v1/pets/{owner}/{repo}/style."""

    async def test_update_style_requires_auth(self, async_client: AsyncClient) -> None:
        """Updating style without auth should return 401."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "authowner", "repo_name": "authrepo", "name": "AuthPet"},
        )
        response = await async_client.put(
            "/api/v1/pets/authowner/authrepo/style",
            json={"style": "wizard"},
        )
        assert response.status_code == 401

    async def test_update_style_invalid_value(self, async_client: AsyncClient) -> None:
        """Sending an invalid style value should return 422 when auth succeeds."""
        from github_tamagotchi.api.auth import get_current_user
        from github_tamagotchi.core.database import get_session
        from tests.conftest import create_api_test_app, get_test_session

        mock_user = MagicMock()
        mock_user.id = 99
        mock_user.is_admin = True  # admin can update any pet

        app = create_api_test_app()
        app.dependency_overrides[get_session] = get_test_session
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Create pet
            await client.post(
                "/api/v1/pets",
                json={"repo_owner": "valowner", "repo_name": "valrepo", "name": "ValPet"},
            )
            response = await client.put(
                "/api/v1/pets/valowner/valrepo/style",
                json={"style": "not_a_real_style"},
            )
        assert response.status_code == 422
