"""RevenueCat server-side entitlement verification.

Context: chat.py and scan.py previously trusted a client-supplied
`is_pro: bool` at face value, with nothing checking it against a real
purchase. A raw HTTP request with `is_pro: true` and no purchase behind it
got unlimited AI-mechanic and receipt-scan usage. This module closes that
gap by checking the claim against RevenueCat's own subscriber record.

Response shape verified against RevenueCat's public API reference before
writing this (not assumed from memory): GET /v1/subscribers/{app_user_id}
returns `subscriber.entitlements`, a dict keyed by entitlement id, and
crucially *expired entitlements are not removed from this dict* — each
entry has to be checked against `expires_date` (null means "does not
expire", e.g. a lifetime/non-renewing purchase) and, if present,
`grace_period_expires_date`. A subscriber with no purchase history still
returns 200 with an empty `entitlements: {}`, not a 404.

One judgment call worth flagging explicitly: whether a grace-period
entitlement (a lapsed renewal RevenueCat is still holding open while a
retry is pending) counts as "active" isn't something I could confirm
against RevenueCat's docs with certainty. This treats it as active,
matching what the client's own `entitlements.active` check already does
today (main.dart's SubscriptionService) — the alternative (ignoring grace
period server-side) would create a real inconsistency: a legitimately
lapsed-card subscriber would see "Pro" in the app while the backend
quietly rate-limited them. If that assumption is wrong, the fix is
localized to `_entitlement_is_active` below.
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_REVENUECAT_API_BASE = "https://api.revenuecat.com/v1"

# In-memory cache, same pattern already used for TecDoc responses
# (tecdoc.py's module-level _cache). {app_user_id: (is_active, checked_at)}
_cache: dict[str, tuple[bool, float]] = {}


def verification_enabled() -> bool:
    """Kill switch. False when REVENUECAT_SECRET_KEY is unset/empty —
    callers must then fall back to the legacy client-trust path entirely,
    not call verify_entitlement() at all. This is an emergency/
    compatibility escape hatch, not the intended steady state: it exists
    so a bad key or a RevenueCat-side problem can be worked around by
    clearing one Railway env var, without a code deploy.
    """
    return bool(settings.revenuecat_secret_key)


async def verify_entitlement(app_user_id: str) -> bool:
    """Return True only if `app_user_id` currently has an active
    entitlement per RevenueCat.

    Returns False for: no purchase history, an expired entitlement with
    no active grace period, AND any verification failure (timeout,
    network error, unexpected response shape, RevenueCat outage). This
    function never raises — callers must treat every False the same way,
    as "apply free-tier limits for this request". Never treat False as
    grounds to deny the request outright, and never treat a verification
    failure as grounds to grant unlimited access.
    """
    now = time.monotonic()
    cached = _cache.get(app_user_id)
    if cached is not None:
        is_active, checked_at = cached
        if now - checked_at < settings.revenuecat_verification_cache_ttl_seconds:
            return is_active

    is_active = await _fetch_entitlement_status(app_user_id)
    _cache[app_user_id] = (is_active, now)
    return is_active


async def _fetch_entitlement_status(app_user_id: str) -> bool:
    url = f"{_REVENUECAT_API_BASE}/subscribers/{app_user_id}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {settings.revenuecat_secret_key}"},
            )
    except httpx.RequestError:
        logger.warning(
            "RevenueCat verification request failed (network error); "
            "treating as free tier for this request"
        )
        return False

    if response.status_code not in (200, 201):
        # Deliberately not logging response.text: it may contain
        # subscriber data, and detail messages could echo back the
        # Authorization header's key material in some error paths.
        logger.warning(
            "RevenueCat verification returned unexpected status %s; "
            "treating as free tier for this request",
            response.status_code,
        )
        return False

    try:
        entitlements = response.json()["subscriber"]["entitlements"]
    except (KeyError, ValueError, TypeError):
        logger.warning(
            "RevenueCat verification response had an unexpected shape; "
            "treating as free tier for this request"
        )
        return False

    entitlement = entitlements.get(settings.revenuecat_entitlement_id)
    if entitlement is None:
        return False
    return _entitlement_is_active(entitlement)


def _entitlement_is_active(entitlement: dict) -> bool:
    now = datetime.now(timezone.utc)
    expires = _parse_iso8601(entitlement.get("expires_date"))
    if expires is None:
        return True  # lifetime / non-renewing purchase — never expires
    if expires > now:
        return True
    grace = _parse_iso8601(entitlement.get("grace_period_expires_date"))
    return grace is not None and grace > now


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
