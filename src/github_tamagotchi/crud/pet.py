"""Backwards-compatibility shim: re-exports from repositories.pet.

All callers that import from ``crud.pet`` continue to work unchanged.
New code should import from ``repositories.pet`` or ``services.pet`` directly.
"""

from github_tamagotchi.repositories.pet import (
    _LEADERBOARD_CACHE_TTL_SECONDS as _LEADERBOARD_CACHE_TTL_SECONDS,
)
from github_tamagotchi.repositories.pet import (
    _leaderboard_cache as _leaderboard_cache,
)
from github_tamagotchi.repositories.pet import (
    create_pet as create_pet,
)
from github_tamagotchi.repositories.pet import (
    delete_pet as delete_pet,
)
from github_tamagotchi.repositories.pet import (
    feed_pet as feed_pet,
)
from github_tamagotchi.repositories.pet import (
    get_all as get_all,
)
from github_tamagotchi.repositories.pet import (
    get_leaderboard as get_leaderboard,
)
from github_tamagotchi.repositories.pet import (
    get_org_pets as get_org_pets,
)
from github_tamagotchi.repositories.pet import (
    get_pet_by_repo as get_pet_by_repo,
)
from github_tamagotchi.repositories.pet import (
    get_pets as get_pets,
)
from github_tamagotchi.repositories.pet import (
    get_pets_by_github_username as get_pets_by_github_username,
)
from github_tamagotchi.repositories.pet import (
    get_pets_with_owners as get_pets_with_owners,
)
from github_tamagotchi.repositories.pet import (
    reset_pet as reset_pet,
)
from github_tamagotchi.repositories.pet import (
    resurrect_pet as resurrect_pet,
)
from github_tamagotchi.repositories.pet import (
    save as save,
)
from github_tamagotchi.repositories.pet import (
    select_skin as select_skin,
)
from github_tamagotchi.repositories.pet import (
    update_canonical_appearance as update_canonical_appearance,
)
from github_tamagotchi.repositories.pet import (
    update_images_generated_at as update_images_generated_at,
)
