"""Backwards-compatibility shim: re-exports from repositories.contributor.

All callers that import from ``crud.contributor_relationship`` continue to work unchanged.
New code should import from ``repositories.contributor`` directly.
"""

from github_tamagotchi.repositories.contributor import (
    apply_score_delta as apply_score_delta,
)
from github_tamagotchi.repositories.contributor import (
    get_contributors_for_pet as get_contributors_for_pet,
)
from github_tamagotchi.repositories.contributor import (
    upsert_contributor_relationship as upsert_contributor_relationship,
)
