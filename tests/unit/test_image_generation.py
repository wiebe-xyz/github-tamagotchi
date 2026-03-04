"""Tests for the ComfyUI image generation service."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.services.image_generation import (
    BODY_TYPES,
    COLOR_PALETTES,
    FEATURES,
    NEGATIVE_PROMPT,
    STAGE_PROMPTS,
    GenerationResult,
    ImageGenerationService,
    PetAppearance,
    build_prompt,
    build_workflow,
    get_pet_appearance,
    load_base_workflow,
    repo_to_seed,
)


class TestRepoToSeed:
    """Tests for deterministic seed generation."""

    def test_same_repo_produces_same_seed(self) -> None:
        """Same owner/repo should always produce the same seed."""
        seed1 = repo_to_seed("octocat", "hello-world")
        seed2 = repo_to_seed("octocat", "hello-world")
        assert seed1 == seed2

    def test_different_repos_produce_different_seeds(self) -> None:
        """Different repositories should produce different seeds."""
        seed1 = repo_to_seed("octocat", "hello-world")
        seed2 = repo_to_seed("octocat", "goodbye-world")
        assert seed1 != seed2

    def test_case_insensitive(self) -> None:
        """Seed should be case insensitive."""
        seed1 = repo_to_seed("OctoCat", "Hello-World")
        seed2 = repo_to_seed("octocat", "hello-world")
        assert seed1 == seed2

    def test_seed_is_32bit_integer(self) -> None:
        """Seed should fit in a 32-bit unsigned integer."""
        seed = repo_to_seed("some-owner", "some-repo")
        assert 0 <= seed < 2**32


class TestGetPetAppearance:
    """Tests for pet appearance derivation."""

    def test_returns_pet_appearance(self) -> None:
        """Should return a PetAppearance dataclass."""
        appearance = get_pet_appearance("octocat", "hello-world")
        assert isinstance(appearance, PetAppearance)

    def test_appearance_is_deterministic(self) -> None:
        """Same repo should always have same appearance."""
        appearance1 = get_pet_appearance("octocat", "hello-world")
        appearance2 = get_pet_appearance("octocat", "hello-world")

        assert appearance1.color == appearance2.color
        assert appearance1.accent_color == appearance2.accent_color
        assert appearance1.body_type == appearance2.body_type
        assert appearance1.feature == appearance2.feature
        assert appearance1.seed == appearance2.seed

    def test_appearance_uses_valid_values(self) -> None:
        """Appearance should use values from defined palettes and types."""
        appearance = get_pet_appearance("test-owner", "test-repo")

        # Check color is from palette
        valid_colors = [c[0] for c in COLOR_PALETTES]
        assert appearance.color in valid_colors

        # Check accent is from palette
        valid_accents = [c[1] for c in COLOR_PALETTES]
        assert appearance.accent_color in valid_accents

        # Check body type
        assert appearance.body_type in BODY_TYPES

        # Check feature
        assert appearance.feature in FEATURES


class TestBuildPrompt:
    """Tests for prompt generation."""

    def test_builds_prompt_with_all_fields(self) -> None:
        """Prompt should include all appearance and stage details."""
        appearance = PetAppearance(
            color="sky blue",
            accent_color="white",
            body_type="round blob",
            feature="small antenna",
            seed=12345,
        )
        prompt = build_prompt(appearance, PetStage.BABY.value)

        assert "sky blue" in prompt
        assert "white" in prompt
        assert "round blob" in prompt
        assert "small antenna" in prompt
        assert "oversized head" in prompt  # From BABY stage description

    def test_all_stages_have_descriptions(self) -> None:
        """All pet stages should have corresponding descriptions."""
        for stage in PetStage:
            assert stage.value in STAGE_PROMPTS

    def test_default_stage_used_for_unknown(self) -> None:
        """Unknown stage should fall back to adult description."""
        appearance = PetAppearance(
            color="pink",
            accent_color="lavender",
            body_type="oval",
            feature="tiny wings",
            seed=999,
        )
        prompt = build_prompt(appearance, "unknown_stage")

        # Should use adult stage as default
        assert "full grown creature" in prompt


class TestLoadBaseWorkflow:
    """Tests for workflow loading."""

    def test_loads_valid_json(self) -> None:
        """Should load workflow JSON successfully."""
        workflow = load_base_workflow()
        assert isinstance(workflow, dict)

    def test_workflow_has_required_nodes(self) -> None:
        """Workflow should contain all required ComfyUI nodes."""
        workflow = load_base_workflow()

        # Check for key nodes
        assert "3" in workflow  # KSampler
        assert "4" in workflow  # CheckpointLoader
        assert "5" in workflow  # EmptyLatentImage
        assert "6" in workflow  # CLIPTextEncode (positive)
        assert "7" in workflow  # CLIPTextEncode (negative)
        assert "8" in workflow  # VAEDecode
        assert "9" in workflow  # ImageScale
        assert "10" in workflow  # SaveImage

    def test_workflow_ksampler_configuration(self) -> None:
        """KSampler should have reasonable default configuration."""
        workflow = load_base_workflow()
        ksampler = workflow["3"]["inputs"]

        assert ksampler["cfg"] == 7.5
        assert ksampler["steps"] == 25
        assert ksampler["sampler_name"] == "euler_ancestral"

    def test_workflow_outputs_512x512(self) -> None:
        """Image should be scaled to 512x512."""
        workflow = load_base_workflow()
        scale = workflow["9"]["inputs"]

        assert scale["width"] == 512
        assert scale["height"] == 512


class TestBuildWorkflow:
    """Tests for complete workflow building."""

    def test_builds_complete_workflow(self) -> None:
        """Should build a complete workflow from repo details."""
        workflow = build_workflow("octocat", "hello-world", PetStage.ADULT.value)

        assert isinstance(workflow, dict)
        assert len(workflow) > 0

    def test_sets_seed_from_repo(self) -> None:
        """Seed should be derived from repository."""
        workflow = build_workflow("octocat", "hello-world", PetStage.ADULT.value)
        expected_seed = repo_to_seed("octocat", "hello-world")

        assert workflow["3"]["inputs"]["seed"] == expected_seed

    def test_sets_positive_prompt(self) -> None:
        """Positive prompt should be set based on appearance and stage."""
        workflow = build_workflow("test-owner", "test-repo", PetStage.EGG.value)
        prompt = workflow["6"]["inputs"]["text"]

        # Should contain stage description
        assert "egg" in prompt.lower() or "oval" in prompt.lower()
        # Should contain kawaii/tamagotchi styling
        assert "kawaii" in prompt.lower()

    def test_sets_filename_prefix(self) -> None:
        """Filename prefix should include owner, repo, and stage."""
        workflow = build_workflow("myowner", "myrepo", PetStage.TEEN.value)
        prefix = workflow["10"]["inputs"]["filename_prefix"]

        assert prefix == "myowner_myrepo_teen"


class TestNegativePrompt:
    """Tests for negative prompt content."""

    def test_negative_prompt_excludes_unwanted_content(self) -> None:
        """Negative prompt should exclude undesirable image qualities."""
        assert "blurry" in NEGATIVE_PROMPT
        assert "realistic" in NEGATIVE_PROMPT
        assert "horror" in NEGATIVE_PROMPT
        assert "watermark" in NEGATIVE_PROMPT


class TestImageGenerationService:
    """Tests for the ImageGenerationService class."""

    @pytest.fixture
    def service(self) -> ImageGenerationService:
        """Create a test service instance."""
        return ImageGenerationService(comfyui_url="http://test-comfyui:8188")

    @pytest.mark.asyncio
    async def test_generate_success(self, service: ImageGenerationService) -> None:
        """Should return success result when generation works."""
        mock_image_data = b"\x89PNG\r\n\x1a\n"  # PNG header

        with (
            patch.object(service, "_queue_prompt", return_value="test-prompt-id"),
            patch.object(service, "_wait_for_image", return_value=mock_image_data),
        ):
            result = await service.generate_pet_image("owner", "repo", "adult")

        assert result.success is True
        assert result.image_data == mock_image_data
        assert result.filename == "owner_repo_adult.png"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_generate_queue_failure(self, service: ImageGenerationService) -> None:
        """Should return error when prompt queuing fails."""
        with patch.object(service, "_queue_prompt", return_value=None):
            result = await service.generate_pet_image("owner", "repo", "baby")

        assert result.success is False
        assert result.error == "Failed to queue prompt in ComfyUI"
        assert result.image_data is None

    @pytest.mark.asyncio
    async def test_generate_image_retrieval_failure(self, service: ImageGenerationService) -> None:
        """Should return error when image retrieval fails."""
        with (
            patch.object(service, "_queue_prompt", return_value="test-prompt-id"),
            patch.object(service, "_wait_for_image", return_value=None),
        ):
            result = await service.generate_pet_image("owner", "repo", "child")

        assert result.success is False
        assert result.error is not None
        assert "retrieve" in result.error.lower()

    @pytest.mark.asyncio
    async def test_generate_timeout(self, service: ImageGenerationService) -> None:
        """Should handle timeout errors gracefully."""
        with patch.object(service, "_queue_prompt", side_effect=httpx.TimeoutException("Timeout")):
            result = await service.generate_pet_image("owner", "repo", "teen")

        assert result.success is False
        assert result.error is not None
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_generate_generic_error(self, service: ImageGenerationService) -> None:
        """Should handle generic errors gracefully."""
        with patch.object(service, "_queue_prompt", side_effect=Exception("Connection refused")):
            result = await service.generate_pet_image("owner", "repo", "elder")

        assert result.success is False
        assert result.error is not None
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_check_health_success(self, service: ImageGenerationService) -> None:
        """Should return True when ComfyUI is healthy."""
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await service.check_health()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self, service: ImageGenerationService) -> None:
        """Should return False when ComfyUI is unreachable."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            result = await service.check_health()

        assert result is False


class TestGenerationResult:
    """Tests for GenerationResult dataclass."""

    def test_success_result(self) -> None:
        """Should create a successful result."""
        result = GenerationResult(
            success=True,
            image_data=b"test",
            filename="test.png",
        )
        assert result.success is True
        assert result.image_data == b"test"
        assert result.filename == "test.png"
        assert result.error is None

    def test_failure_result(self) -> None:
        """Should create a failure result."""
        result = GenerationResult(
            success=False,
            error="Something went wrong",
        )
        assert result.success is False
        assert result.image_data is None
        assert result.filename is None
        assert result.error == "Something went wrong"
