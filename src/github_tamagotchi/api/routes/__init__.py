# ruff: noqa: I001
"""Domain-scoped API routers.

This package replaces the monolithic api/routes.py. Each module owns one domain.
All routers share the /api/v1 prefix (set per-router).

The symbols below (settings, StorageService, etc.) are re-exported at this package
level so that existing test patches targeting ``github_tamagotchi.api.routes.<name>``
continue to work without modification.  Sub-modules that need these symbols should
import them via ``import github_tamagotchi.api.routes as _api_routes`` and then
reference ``_api_routes.<name>`` so they always read the (possibly-patched) attribute
from this module rather than a locally cached binding.
"""

# Re-export patchable symbols BEFORE importing sub-modules so that when sub-modules
# do ``import github_tamagotchi.api.routes as _api_routes`` during their own init,
# these attributes are already present on the partially-initialised package object.
from github_tamagotchi.core.config import settings  # noqa: F401
from github_tamagotchi.services import image_queue  # noqa: F401
from github_tamagotchi.services.github import GitHubService  # noqa: F401
from github_tamagotchi.services.image_queue import get_image_provider  # noqa: F401
from github_tamagotchi.services.openrouter import OpenRouterService  # noqa: F401
from github_tamagotchi.services.storage import StorageService  # noqa: F401
from github_tamagotchi.services.token_encryption import decrypt_token  # noqa: F401

# Domain sub-routers — imported after the patchable symbols so that sub-modules
# can safely reference ``_api_routes.<symbol>`` during their own import.
from fastapi import APIRouter

from github_tamagotchi.api.routes import (
    admin,
    pets_actions,
    pets_appearance,
    pets_crud,
    pets_info,
    pets_media,
    social,
    system,
    webhooks,
)

# Aggregate router — registered on the main app instead of the old routes.router
router = APIRouter()

router.include_router(pets_crud.router)
router.include_router(pets_appearance.router)
router.include_router(pets_media.router)
router.include_router(pets_info.router)
router.include_router(pets_actions.router)
router.include_router(admin.router)
router.include_router(social.router)
router.include_router(system.router)
router.include_router(webhooks.router)
