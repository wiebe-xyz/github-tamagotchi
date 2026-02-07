"""Tests for ComfyUI image generation service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.services.image_generation import (
    COLORS,
    PATTERNS,
    SPECIES,
    STAGE_DESCRIPTIONS,
    ImageGenerationService,
    build_comfyui_workflow,
    generate_pet_prompt,
    get_pet_characteristics,
    get_repo_hash,
    get_seed_from_hash,
)


class TestPromptGeneration:
    """Tests for prompt generation functions."""

    def test_get_repo_hash_deterministic(self) -> None:
        """Test that repo hash is deterministic."""
        hash1 = get_repo_hash("owner", "repo")
        hash2 = get_repo_hash("owner", "repo")
        assert hash1 == hash2

    def test_get_repo_hash_different_repos(self) -> None:
        """Test that different repos get different hashes."""
        hash1 = get_repo_hash("owner", "repo1")
        hash2 = get_repo_hash("owner", "repo2")
        assert hash1 != hash2

    def test_get_seed_from_hash_deterministic(self) -> None:
        """Test that seed generation is deterministic."""
        hash_bytes = get_repo_hash("test", "repo")
        seed1 = get_seed_from_hash(hash_bytes)
        seed2 = get_seed_from_hash(hash_bytes)
        assert seed1 == seed2

    def test_get_seed_from_hash_is_integer(self) -> None:
        """Test that seed is a valid integer."""
        hash_bytes = get_repo_hash("test", "repo")
        seed = get_seed_from_hash(hash_bytes)
        assert isinstance(seed, int)
        assert seed >= 0

    def test_get_pet_characteristics_deterministic(self) -> None:
        """Test that characteristics are deterministic per repo."""
        chars1 = get_pet_characteristics("owner", "repo")
        chars2 = get_pet_characteristics("owner", "repo")
        assert chars1 == chars2

    def test_get_pet_characteristics_has_required_keys(self) -> None:
        """Test that characteristics has all required keys."""
        chars = get_pet_characteristics("test", "repo")
        assert "color" in chars
        assert "pattern" in chars
        assert "species" in chars

    def test_get_pet_characteristics_valid_values(self) -> None:
        """Test that characteristics use valid values from lists."""
        chars = get_pet_characteristics("test", "repo")
        assert chars["color"] in COLORS
        assert chars["pattern"] in PATTERNS
        assert chars["species"] in SPECIES

    def test_generate_pet_prompt_contains_characteristics(self) -> None:
        """Test that prompt includes pet characteristics."""
        prompt = generate_pet_prompt("owner", "repo", "egg")
        chars = get_pet_characteristics("owner", "repo")

        assert chars["color"] in prompt
        assert chars["pattern"] in prompt
        assert chars["species"] in prompt

    def test_generate_pet_prompt_contains_stage_description(self) -> None:
        """Test that prompt includes stage-specific description."""
        for stage in PetStage:
            prompt = generate_pet_prompt("owner", "repo", stage.value)
            stage_desc = STAGE_DESCRIPTIONS[stage.value]
            assert stage_desc in prompt

    def test_generate_pet_prompt_has_style_keywords(self) -> None:
        """Test that prompt includes required style keywords."""
        prompt = generate_pet_prompt("owner", "repo", "baby")
        assert "pixel art" in prompt
        assert "tamagotchi" in prompt
        assert "kawaii" in prompt
        assert "white background" in prompt

    def test_build_comfyui_workflow_structure(self) -> None:
        """Test that workflow has correct structure."""
        workflow = build_comfyui_workflow("owner", "repo", "egg")

        # Check required nodes exist
        assert "3" in workflow  # KSampler
        assert "4" in workflow  # CheckpointLoader
        assert "5" in workflow  # EmptyLatentImage
        assert "6" in workflow  # Positive prompt
        assert "7" in workflow  # Negative prompt
        assert "8" in workflow  # VAEDecode
        assert "9" in workflow  # SaveImage

    def test_build_comfyui_workflow_uses_repo_seed(self) -> None:
        """Test that workflow uses deterministic seed from repo."""
        workflow1 = build_comfyui_workflow("owner", "repo", "egg")
        workflow2 = build_comfyui_workflow("owner", "repo", "egg")

        assert workflow1["3"]["inputs"]["seed"] == workflow2["3"]["inputs"]["seed"]

    def test_build_comfyui_workflow_different_seeds_per_repo(self) -> None:
        """Test that different repos get different seeds."""
        workflow1 = build_comfyui_workflow("owner", "repo1", "egg")
        workflow2 = build_comfyui_workflow("owner", "repo2", "egg")

        assert workflow1["3"]["inputs"]["seed"] != workflow2["3"]["inputs"]["seed"]

    def test_build_comfyui_workflow_contains_prompt(self) -> None:
        """Test that workflow contains the generated prompt."""
        workflow = build_comfyui_workflow("owner", "repo", "baby")
        prompt = generate_pet_prompt("owner", "repo", "baby")

        assert workflow["6"]["inputs"]["text"] == prompt

    def test_build_comfyui_workflow_filename_prefix(self) -> None:
        """Test that output filename includes repo info."""
        workflow = build_comfyui_workflow("owner", "repo", "adult")

        filename = workflow["9"]["inputs"]["filename_prefix"]
        assert "owner" in filename
        assert "repo" in filename
        assert "adult" in filename


class TestImageGenerationService:
    """Tests for ImageGenerationService."""

    @pytest.fixture
    def mock_storage(self) -> MagicMock:
        """Create a mock storage service."""
        storage = MagicMock()
        storage.upload_image = AsyncMock(return_value="pets/owner/repo/egg.png")
        storage.get_image = AsyncMock(return_value=None)
        storage.delete_images = AsyncMock()
        return storage

    @pytest.fixture
    def image_service(self, mock_storage: MagicMock) -> ImageGenerationService:
        """Create image generation service with mocked dependencies."""
        return ImageGenerationService(
            comfyui_url="http://localhost:8188",
            timeout=60,
            storage=mock_storage,
        )

    def test_service_initialization_defaults(self) -> None:
        """Test service uses settings defaults when not provided."""
        with patch("github_tamagotchi.services.image_generation.settings") as mock_settings:
            mock_settings.comfyui_url = "http://test:8188"
            mock_settings.comfyui_timeout_seconds = 120

            service = ImageGenerationService()

            assert service.comfyui_url == "http://test:8188"
            assert service.timeout == 120

    def test_service_initialization_custom_values(
        self, mock_storage: MagicMock
    ) -> None:
        """Test service uses provided values."""
        service = ImageGenerationService(
            comfyui_url="http://custom:9999",
            timeout=30,
            storage=mock_storage,
        )

        assert service.comfyui_url == "http://custom:9999"
        assert service.timeout == 30

    @respx.mock
    async def test_generate_stage_image_success(
        self, image_service: ImageGenerationService
    ) -> None:
        """Test successful image generation."""
        prompt_response = {"prompt_id": "test-prompt-123"}
        history_response = {
            "test-prompt-123": {
                "status": {"completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "test.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                },
            }
        }
        image_data = b"fake png image data"

        respx.post("http://localhost:8188/prompt").mock(
            return_value=httpx.Response(200, json=prompt_response)
        )
        respx.get("http://localhost:8188/history/test-prompt-123").mock(
            return_value=httpx.Response(200, json=history_response)
        )
        respx.get("http://localhost:8188/view").mock(
            return_value=httpx.Response(200, content=image_data)
        )

        result = await image_service.generate_stage_image("owner", "repo", "egg")

        assert result == image_data

    async def test_generate_stage_image_no_url_raises(
        self, mock_storage: MagicMock
    ) -> None:
        """Test that missing URL raises error."""
        service = ImageGenerationService(
            comfyui_url=None,
            storage=mock_storage,
        )

        with pytest.raises(ValueError, match="ComfyUI URL not configured"):
            await service.generate_stage_image("owner", "repo", "egg")

    @respx.mock
    async def test_generate_stage_image_timeout(
        self, mock_storage: MagicMock
    ) -> None:
        """Test generation timeout."""
        service = ImageGenerationService(
            comfyui_url="http://localhost:8188",
            timeout=1,
            storage=mock_storage,
        )

        respx.post("http://localhost:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "test-123"})
        )
        respx.get("http://localhost:8188/history/test-123").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.raises(TimeoutError):
            await service.generate_stage_image("owner", "repo", "egg")

    async def test_generate_all_stages(
        self, image_service: ImageGenerationService, mock_storage: MagicMock
    ) -> None:
        """Test generating all stage images in parallel."""
        image_service.generate_stage_image = AsyncMock(return_value=b"image data")

        result = await image_service.generate_all_stages("owner", "repo")

        assert len(result) == 6
        assert set(result.keys()) == {"egg", "baby", "child", "teen", "adult", "elder"}
        assert image_service.generate_stage_image.call_count == 6
        assert mock_storage.upload_image.call_count == 6

    async def test_get_or_generate_image_cached(
        self, image_service: ImageGenerationService, mock_storage: MagicMock
    ) -> None:
        """Test returning cached image."""
        cached_data = b"cached image"
        mock_storage.get_image.return_value = cached_data

        result = await image_service.get_or_generate_image("owner", "repo", "egg")

        assert result == cached_data
        mock_storage.get_image.assert_called_once_with("owner", "repo", "egg")

    async def test_get_or_generate_image_generates_when_not_cached(
        self, image_service: ImageGenerationService, mock_storage: MagicMock
    ) -> None:
        """Test generating image when not cached."""
        mock_storage.get_image.return_value = None
        generated_data = b"generated image"
        image_service.generate_stage_image = AsyncMock(return_value=generated_data)

        result = await image_service.get_or_generate_image("owner", "repo", "baby")

        assert result == generated_data
        mock_storage.upload_image.assert_called_once_with(
            "owner", "repo", "baby", generated_data
        )

    async def test_regenerate_images_deletes_first(
        self, image_service: ImageGenerationService, mock_storage: MagicMock
    ) -> None:
        """Test that regenerate deletes existing images first."""
        image_service.generate_all_stages = AsyncMock(return_value={"egg": "path"})

        await image_service.regenerate_images("owner", "repo")

        mock_storage.delete_images.assert_called_once_with("owner", "repo")
        image_service.generate_all_stages.assert_called_once_with("owner", "repo")


class TestCharacteristicsDistribution:
    """Tests to verify characteristics have good distribution."""

    def test_colors_cover_multiple_values(self) -> None:
        """Test that different repos get different colors."""
        colors_seen = set()
        for i in range(100):
            chars = get_pet_characteristics(f"owner{i}", "repo")
            colors_seen.add(chars["color"])

        # Should see at least half the available colors in 100 repos
        assert len(colors_seen) >= len(COLORS) // 2

    def test_species_cover_multiple_values(self) -> None:
        """Test that different repos get different species."""
        species_seen = set()
        for i in range(100):
            chars = get_pet_characteristics(f"owner{i}", "repo")
            species_seen.add(chars["species"])

        assert len(species_seen) >= len(SPECIES) // 2

    def test_patterns_cover_multiple_values(self) -> None:
        """Test that different repos get different patterns."""
        patterns_seen = set()
        for i in range(100):
            chars = get_pet_characteristics(f"owner{i}", "repo")
            patterns_seen.add(chars["pattern"])

        assert len(patterns_seen) >= len(PATTERNS) // 2
