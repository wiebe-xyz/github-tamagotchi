# ruff: noqa: I001
"""Domain-scoped API routers (versioned).

This package replaces the monolithic api/routes.py. Routes live under v1/,
with domain sub-packages mirroring the URL hierarchy:

  v1/pets/crud.py        → /api/v1/pets/...
  v1/pets/appearance.py  → PUT style, name, badge-style, skins
  v1/pets/media.py       → badge SVG, images, animated GIFs
  v1/pets/info.py        → characteristics, comments, achievements, …
  v1/pets/actions.py     → resurrect
  v1/admin.py            → pet admin settings, exclusions, reset
  v1/social.py           → leaderboard, showcase, contributor badge
  v1/system.py           → styles, badge-styles, health, queue stats
  v1/webhooks.py         → GitHub webhook receiver

The symbols below are re-exported at this package level so that existing
test patches targeting ``github_tamagotchi.api.routes.<name>`` continue to
work without modification.  Sub-modules access them via
``import github_tamagotchi.api.routes as _api_routes`` so they always read
the (possibly-patched) attribute from this module.
"""

# Re-export patchable symbols BEFORE importing sub-modules so they are
# already present on the partially-initialised package object when sub-modules
# do ``import github_tamagotchi.api.routes as _api_routes`` during their init.
from github_tamagotchi.core.config import settings as settings
from github_tamagotchi.services import image_queue as image_queue
from github_tamagotchi.services.github import GitHubService as GitHubService
from github_tamagotchi.services.image_queue import get_image_provider as get_image_provider
from github_tamagotchi.services.openrouter import OpenRouterService as OpenRouterService
from github_tamagotchi.services.storage import StorageService as StorageService
from github_tamagotchi.services.token_encryption import decrypt_token as decrypt_token

from fastapi import APIRouter

from github_tamagotchi.api.routes.v1.pets import (
    actions,
    appearance,
    crud,
    info,
    media,
)
from github_tamagotchi.api.routes.v1 import (
    admin,
    social,
    system,
    webhooks,
)

# Aggregate router — registered on the main app instead of the old routes.router
router: APIRouter = APIRouter()

router.include_router(crud.router)
router.include_router(appearance.router)
router.include_router(media.router)
router.include_router(info.router)
router.include_router(actions.router)
router.include_router(admin.router)
router.include_router(social.router)
router.include_router(system.router)
router.include_router(webhooks.router)
