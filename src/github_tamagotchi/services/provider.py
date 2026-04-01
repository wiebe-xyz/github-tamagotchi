"""Image generation provider protocol."""

from typing import Protocol, runtime_checkable

from github_tamagotchi.services.image_generation import GenerationResult


@runtime_checkable
class ImageProvider(Protocol):
    """Protocol for image generation providers."""

    async def generate_pet_image(
        self, owner: str, repo: str, stage: str
    ) -> GenerationResult:
        """Generate a pet image for the given repository and stage."""
        ...

    async def check_health(self) -> bool:
        """Check if the provider is available and healthy."""
        ...
