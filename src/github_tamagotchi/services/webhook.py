"""GitHub webhook processing service."""

import asyncio
import hashlib
import hmac
import ipaddress
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.crud.contributor_relationship import apply_score_delta
from github_tamagotchi.crud.milestone import create_milestone
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.pet_logic import get_next_stage

_tracer = get_tracer(__name__)

_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# GitHub publishes the IP ranges it sends webhook deliveries from at this
# public, unauthenticated endpoint (the "hooks" key). We trust source IP
# instead of a shared secret: setting up your own webhook secret per repo
# isn't practical here (there's one bot-wide secret, and handing it out
# would let any repo forge deliveries for any other), and unlike a header a
# client sends, the TCP source IP can't be forged by a random request over
# the open internet -- completing our TLS handshake requires actually
# holding that address. See issue #278/#279.
_GITHUB_META_URL = "https://api.github.com/meta"
_RANGES_CACHE_TTL_SECONDS = 3600

# One CI run on a busy repo sends dozens of check_run/pull_request events within a
# minute. Every handler updates the same pet row, so concurrent handlers wait on each
# other's row locks while each holds a pool connection, and the pool (5 + 10 overflow)
# runs dry (BugBarn GT-36). Handlers for one repo run one at a time, queued here before
# they take a connection.
_repo_locks: dict[str, tuple[asyncio.Lock, int]] = {}


@asynccontextmanager
async def serialize_repo_events(owner: str, name: str) -> AsyncIterator[None]:
    """Run webhook handling for one repository one event at a time."""
    key = f"{owner}/{name}".lower()
    lock, waiters = _repo_locks.get(key, (asyncio.Lock(), 0))
    _repo_locks[key] = (lock, waiters + 1)
    try:
        async with lock:
            yield
    finally:
        lock, waiters = _repo_locks[key]
        if waiters <= 1:
            del _repo_locks[key]
        else:
            _repo_locks[key] = (lock, waiters - 1)


_cached_networks: list[_IPNetwork] = []
_cached_at: float = 0.0


async def _fetch_github_hook_networks() -> list[_IPNetwork]:
    """Fetch GitHub's currently published webhook-sending IP ranges."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(_GITHUB_META_URL)
        resp.raise_for_status()
        data = resp.json()

    networks: list[_IPNetwork] = []
    for cidr in data.get("hooks", []):
        try:
            networks.append(ipaddress.ip_network(cidr))
        except ValueError:
            continue
    return networks


async def _get_github_hook_networks() -> list[_IPNetwork]:
    """Cached accessor for GitHub's webhook IP ranges, refreshed hourly.

    A fetch failure keeps whatever was last cached (GitHub's ranges change
    rarely; a transient outage shouldn't suddenly reject every delivery).
    If nothing has ever been cached, returns empty -- callers should treat
    that as "can't verify" and fail closed, not as "no restriction".
    """
    global _cached_networks, _cached_at
    now = time.monotonic()
    if _cached_networks and (now - _cached_at) < _RANGES_CACHE_TTL_SECONDS:
        return _cached_networks

    try:
        fetched = await _fetch_github_hook_networks()
    except Exception as e:
        logger.warning("failed to refresh GitHub webhook IP ranges", error=str(e))
        return _cached_networks

    if fetched:
        _cached_networks = fetched
        _cached_at = now
    return _cached_networks


# Cloudflare's published edge ranges (https://www.cloudflare.com/ips/). They
# change rarely, so they are listed here instead of fetched at request time.
_CLOUDFLARE_NETWORKS: tuple[_IPNetwork, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def is_cloudflare_address(ip: str) -> bool:
    """Whether `ip` is a Cloudflare edge address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CLOUDFLARE_NETWORKS)


async def is_github_webhook_source(client_ip: str | None) -> bool:
    """Whether `client_ip` is one of GitHub's published webhook-sending addresses.

    Fails closed: an unparseable/missing IP, or ranges we've never
    successfully fetched, is treated as "not verified" rather than "allow".
    """
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    networks = await _get_github_hook_networks()
    if not networks:
        return False
    return any(addr in net for net in networks)


logger = structlog.get_logger()

# Experience and health rewards for webhook events
PUSH_HEALTH_BONUS = 10
PUSH_EXPERIENCE_BONUS = 20
CI_SUCCESS_HEALTH_BONUS = 5
CI_SUCCESS_EXPERIENCE_BONUS = 10
CI_FAILURE_HEALTH_PENALTY = -5
PR_OPENED_EXPERIENCE_BONUS = 5
PR_MERGED_HEALTH_BONUS = 5
PR_MERGED_EXPERIENCE_BONUS = 15
ISSUE_OPENED_EXPERIENCE_BONUS = 3


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (SHA-256).

    GitHub sends a signature in the X-Hub-Signature-256 header as
    'sha256=<hex_digest>'. We compute the HMAC-SHA256 of the raw body
    using the webhook secret and compare.
    """
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def _extract_repo_from_payload(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Extract repo_owner and repo_name from webhook payload."""
    repository = payload.get("repository")
    if not repository:
        return None

    owner_info = repository.get("owner", {})
    owner = owner_info.get("login")
    name = repository.get("name")

    if not owner or not name:
        return None

    return (owner, name)


async def _apply_evolution(pet: Any, db: AsyncSession) -> tuple[str, str] | None:
    """Check for evolution and apply stage change + milestone if needed.

    Returns (old_stage, new_stage) if evolution occurred, else None.
    """
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage == current_stage:
        return None
    pet.stage = new_stage.value
    await create_milestone(db, pet, current_stage.value, new_stage.value, pet.experience)
    return (current_stage.value, new_stage.value)


async def handle_push_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle push events - feed the pet and grant experience."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.push") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        now = datetime.now(UTC)
        pet.health = min(100, pet.health + PUSH_HEALTH_BONUS)
        pet.experience = pet.experience + PUSH_EXPERIENCE_BONUS
        pet.last_fed_at = now
        pet.mood = PetMood.HAPPY.value

        evolution = await _apply_evolution(pet, db)
        if evolution:
            logger.info(
                "pet_evolved_via_webhook",
                pet_id=pet.id,
                old_stage=evolution[0],
                new_stage=evolution[1],
            )

        # Update contributor score for the pusher
        pusher = payload.get("pusher", {}).get("name") or payload.get("sender", {}).get("login")
        if pusher:
            await apply_score_delta(
                db=db,
                pet_id=pet.id,
                github_username=pusher,
                delta=5,  # SCORE_PER_COMMIT
                event_description="pushed commits",
                now=now,
            )

        await db.commit()

        logger.info(
            "webhook_push_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            new_health=pet.health,
            new_experience=pet.experience,
        )
        return f"push processed for {owner}/{name}"


async def handle_pull_request_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle pull_request events - affect mood based on action."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.pull_request") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")
        now = datetime.now(UTC)

        if action == "opened":
            pet.mood = PetMood.WORRIED.value
            pet.experience = pet.experience + PR_OPENED_EXPERIENCE_BONUS
        elif action == "closed":
            pr = payload.get("pull_request", {})
            if pr.get("merged"):
                pet.mood = PetMood.HAPPY.value
                pet.health = min(100, pet.health + PR_MERGED_HEALTH_BONUS)
                pet.experience = pet.experience + PR_MERGED_EXPERIENCE_BONUS
                # Credit the merger in contributor relationships
                merged_by = (pr.get("merged_by") or {}).get("login")
                if merged_by:
                    await apply_score_delta(
                        db=db,
                        pet_id=pet.id,
                        github_username=merged_by,
                        delta=10,  # SCORE_PER_MERGED_PR
                        event_description="merged a PR",
                        now=now,
                    )
            else:
                # PR closed without merge
                pet.mood = PetMood.CONTENT.value
        elif action == "reopened":
            pet.mood = PetMood.WORRIED.value

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_pr_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            action=action,
            new_mood=pet.mood,
        )
        return f"pull_request ({action}) processed for {owner}/{name}"


async def handle_issues_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle issues events - lonely state for new issues."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.issues") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")

        if action == "opened":
            pet.mood = PetMood.LONELY.value
            pet.experience = pet.experience + ISSUE_OPENED_EXPERIENCE_BONUS
        elif action == "closed":
            pet.mood = PetMood.HAPPY.value

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_issue_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            action=action,
            new_mood=pet.mood,
        )
        return f"issues ({action}) processed for {owner}/{name}"


async def handle_check_run_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle check_run events - CI status affects health and mood."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.check_run") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")
        if action != "completed":
            return f"check_run ({action}) ignored for {owner}/{name}"

        check_run = payload.get("check_run", {})
        conclusion = check_run.get("conclusion", "")
        now = datetime.now(UTC)

        if conclusion == "success":
            pet.health = min(100, pet.health + CI_SUCCESS_HEALTH_BONUS)
            pet.experience = pet.experience + CI_SUCCESS_EXPERIENCE_BONUS
            pet.mood = PetMood.DANCING.value
        elif conclusion in ("failure", "timed_out"):
            pet.health = max(0, pet.health + CI_FAILURE_HEALTH_PENALTY)
            pet.mood = PetMood.WORRIED.value
            # Penalise the person who triggered the failing check
            sender = payload.get("sender", {}).get("login")
            if sender:
                await apply_score_delta(
                    db=db,
                    pet_id=pet.id,
                    github_username=sender,
                    delta=-20,
                    event_description="broke CI",
                    now=now,
                )

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_check_run_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            conclusion=conclusion,
            new_health=pet.health,
            new_mood=pet.mood,
        )
        return f"check_run ({conclusion}) processed for {owner}/{name}"


EVENT_HANDLERS: dict[str, Any] = {
    "push": handle_push_event,
    "pull_request": handle_pull_request_event,
    "issues": handle_issues_event,
    "check_run": handle_check_run_event,
}
