"""Baseline behavior for the AI mechanic chat endpoints
(app/api/v1/endpoints/chat.py, app/services/anthropic_chat.py).

Mocks the outbound call to Anthropic's Messages API.
"""
import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _anthropic_reply(text: str = "Sjekk oljenivået og bremseklossene."):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_get_limit_fresh_device_has_full_quota(client, device_id):
    res = client.get("/api/v1/chat/limit", params={"device_id": device_id})
    assert res.status_code == 200
    assert res.json() == {"used_count": 0, "limit": 3, "remaining": 3}


def test_mechanic_success_free_user_returns_reply_and_updated_count(
    client, respx_mock, device_id
):
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    res = client.post(
        "/api/v1/chat/mechanic",
        json={
            "vehicle": {"merke": "Toyota", "modell": "Corolla"},
            "history": [],
            "message": "Hvorfor blinker oljelampen?",
            "device_id": device_id,
            "is_pro": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "Sjekk oljenivået og bremseklossene."
    assert body["used_count"] == 1
    assert body["limit"] == 3
    assert body["remaining"] == 2


def test_mechanic_free_user_without_device_id_is_rejected(client, respx_mock):
    res = client.post(
        "/api/v1/chat/mechanic",
        json={"message": "test", "is_pro": False},
    )
    assert res.status_code == 400


def test_mechanic_free_user_hits_limit_after_three_messages(
    client, respx_mock, device_id
):
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": False,
    }
    for _ in range(3):
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200

    res = client.post("/api/v1/chat/mechanic", json=body)
    assert res.status_code == 429


def test_mechanic_legacy_request_without_app_user_id_retains_old_behavior(
    client, respx_mock, device_id
):
    """This test used to document the is_pro trust GAP (a raw `is_pro:
    true` bypassing the limit with no verification at all). Work Item C
    closed that gap, but deliberately only when `app_user_id` is present
    — a request in this exact shape (no app_user_id) is precisely what an
    app version that predates the fix still sends, and it must keep
    working exactly as before for backward compatibility. Updating this
    test's meaning rather than deleting it, per the instruction not to
    silently drop the "before" picture.
    """
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,
        # no app_user_id -> legacy path, client's is_pro is trusted as-is
    }
    for _ in range(5):  # comfortably more than the free limit of 3
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200


def test_mechanic_forged_is_pro_with_non_pro_app_user_id_does_not_bypass_limit(
    client, respx_mock, device_id, monkeypatch
):
    """The actual fix, end to end: a request claims is_pro=true AND now
    includes an app_user_id, but that app_user_id has no active
    RevenueCat entitlement (e.g. never purchased, or a fabricated id).
    Verified entitlement must override the forged claim.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "revenuecat_secret_key", "test-revenuecat-secret")
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    respx_mock.get("https://api.revenuecat.com/v1/subscribers/forged-user").mock(
        return_value=httpx.Response(200, json={"subscriber": {"entitlements": {}}})
    )
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,  # forged
        "app_user_id": "forged-user",
    }
    for _ in range(3):
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200

    res = client.post("/api/v1/chat/mechanic", json=body)
    assert res.status_code == 429  # limit enforced despite the forged claim


def test_mechanic_verified_active_entitlement_gets_pro_access(
    client, respx_mock, device_id, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "revenuecat_secret_key", "test-revenuecat-secret")
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    respx_mock.get("https://api.revenuecat.com/v1/subscribers/real-pro-user").mock(
        return_value=httpx.Response(
            200,
            json={
                "subscriber": {
                    "entitlements": {"pro_access": {"expires_date": None}}
                }
            },
        )
    )
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,
        "app_user_id": "real-pro-user",
    }
    for _ in range(5):  # would 429 at free-tier limits if not verified as pro
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200


def test_mechanic_revenuecat_outage_falls_back_to_free_tier_not_unlimited(
    client, respx_mock, device_id, monkeypatch
):
    """Decision from the founder: an outage must not fail open to
    unlimited access, and must not hard-fail the request either — it
    falls back to the same free-tier limit a genuinely non-pro user gets.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "revenuecat_secret_key", "test-revenuecat-secret")
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    respx_mock.get("https://api.revenuecat.com/v1/subscribers/outage-user").mock(
        side_effect=httpx.ConnectError("RevenueCat is down")
    )
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,
        "app_user_id": "outage-user",
    }
    for _ in range(3):
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200  # not hard-failed

    res = client.post("/api/v1/chat/mechanic", json=body)
    assert res.status_code == 429  # not left unlimited either


def test_mechanic_kill_switch_falls_back_to_legacy_trust_when_secret_key_unset(
    client, respx_mock, device_id, monkeypatch
):
    """Emergency/compatibility mechanism: if REVENUECAT_SECRET_KEY is
    empty, verification is skipped entirely (verification_enabled() is
    False) even when the client sends an app_user_id — behavior reverts
    fully to trusting the client's is_pro claim, same as the legacy path.
    This is intentionally NOT the long-term intended behavior; it exists
    so a bad key or a RevenueCat-side problem can be worked around by
    clearing one env var, without a code deploy.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "revenuecat_secret_key", "")
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    # Deliberately no route registered for api.revenuecat.com: if the kill
    # switch didn't work, verify_entitlement would be called and this
    # test would fail via respx rather than silently calling RevenueCat.
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,
        "app_user_id": "irrelevant-user",
    }
    for _ in range(5):
        res = client.post("/api/v1/chat/mechanic", json=body)
        assert res.status_code == 200


def test_mechanic_missing_anthropic_key_fails_fast(client, respx_mock, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    res = client.post(
        "/api/v1/chat/mechanic",
        json={
            "vehicle": {},
            "history": [],
            "message": "hei",
            "is_pro": True,  # is_pro=True skips the rate-limit path so we
            # reach the "missing key" check without needing a device_id
        },
    )
    assert res.status_code == 500
