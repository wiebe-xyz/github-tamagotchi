"""Backwards-compatibility shim: re-exports from repositories.milestone.

All callers that import from ``crud.milestone`` continue to work unchanged.
New code should import from ``repositories.milestone`` directly.
"""

from github_tamagotchi.repositories.milestone import (
    create_milestone as create_milestone,
)
from github_tamagotchi.repositories.milestone import (
    get_latest_milestone as get_latest_milestone,
)
from github_tamagotchi.repositories.milestone import (
    get_milestones as get_milestones,
)
