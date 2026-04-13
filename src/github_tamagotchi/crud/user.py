"""Backwards-compatibility shim: re-exports from repositories.user.

All callers that import from ``crud.user`` continue to work unchanged.
New code should import from ``repositories.user`` or ``services.user`` directly.
"""

from github_tamagotchi.repositories.user import (
    create_or_update_user as create_or_update_user,
)
from github_tamagotchi.repositories.user import (
    get_user_by_github_id as get_user_by_github_id,
)
from github_tamagotchi.repositories.user import (
    get_user_by_id as get_user_by_id,
)
