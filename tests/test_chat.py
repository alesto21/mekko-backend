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


def test_mechanic_pro_flag_bypasses_limit_with_no_server_verification(
    client, respx_mock, device_id
):
    """Documents TODAY'S behavior, which Work Item C exists to close: the
    backend trusts `is_pro` exactly as sent by the client, with no check
    against RevenueCat or any other source of truth. Sending `is_pro:
    true` from a raw HTTP request — with no purchase behind it — grants
    unlimited AI mechanic usage.

    This test is the "before" picture. Once Work Item C ships, this
    assertion should change to reflect verified entitlement instead of a
    raw client claim — don't delete it silently, update it deliberately
    so the diff documents the fix.
    """
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_reply())
    body = {
        "vehicle": {},
        "history": [],
        "message": "hei",
        "device_id": device_id,
        "is_pro": True,
    }
    for _ in range(5):  # comfortably more than the free limit of 3
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
