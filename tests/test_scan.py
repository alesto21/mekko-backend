"""Baseline behavior for receipt-scan endpoints
(app/api/v1/endpoints/scan.py, app/services/anthropic_vision.py).

Mocks the outbound call to Anthropic's Messages API (vision).
"""
import base64

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

FAKE_IMAGE_BASE64 = base64.b64encode(b"not a real image, just test bytes").decode()

VALID_RECEIPT_JSON = (
    '{"date":"2024-03-15","mileage_km":85420,"workshop":"Mekonomen Hønefoss",'
    '"cost_nok":1850.0,"type":"oljeskift","notes":"Oljeskift og nytt filter",'
    '"confidence":"high","is_receipt":true}'
)


def _anthropic_vision_reply(text: str = VALID_RECEIPT_JSON):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_get_scan_limit_fresh_device_has_full_quota(client, device_id):
    res = client.get("/api/v1/scan/limit", params={"device_id": device_id})
    assert res.status_code == 200
    assert res.json() == {"used_count": 0, "limit": 5, "remaining": 5}


def test_scan_receipt_success_free_user(client, respx_mock, device_id):
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_vision_reply())
    res = client.post(
        "/api/v1/scan/receipt",
        json={
            "image_base64": FAKE_IMAGE_BASE64,
            "media_type": "image/jpeg",
            "device_id": device_id,
            "is_pro": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["workshop"] == "Mekonomen Hønefoss"
    assert body["cost_nok"] == 1850.0
    assert body["mileage_km"] == 85420
    assert body["type"] == "oljeskift"
    assert body["is_receipt"] is True
    assert body["used_count"] == 1
    assert body["remaining"] == 4


def test_scan_receipt_non_receipt_image_does_not_count_against_quota(
    client, respx_mock, device_id
):
    """Documents today's deliberate behavior (scan.py comment: "ikke straff
    brukeren... ved en feil"): if Claude decides the image isn't a receipt,
    the free-tier count is NOT incremented.
    """
    non_receipt_json = (
        '{"date":null,"mileage_km":null,"workshop":null,"cost_nok":null,'
        '"type":"annet","notes":null,"confidence":"low","is_receipt":false}'
    )
    respx_mock.post(ANTHROPIC_URL).mock(
        return_value=_anthropic_vision_reply(non_receipt_json)
    )
    res = client.post(
        "/api/v1/scan/receipt",
        json={
            "image_base64": FAKE_IMAGE_BASE64,
            "device_id": device_id,
            "is_pro": False,
        },
    )
    assert res.status_code == 200
    assert res.json()["is_receipt"] is False
    assert res.json()["used_count"] == 0
    assert res.json()["remaining"] == 5


def test_scan_receipt_free_user_hits_limit_after_five_scans(
    client, respx_mock, device_id
):
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_vision_reply())
    body = {
        "image_base64": FAKE_IMAGE_BASE64,
        "device_id": device_id,
        "is_pro": False,
    }
    for _ in range(5):
        res = client.post("/api/v1/scan/receipt", json=body)
        assert res.status_code == 200

    res = client.post("/api/v1/scan/receipt", json=body)
    assert res.status_code == 429


def test_scan_receipt_pro_flag_bypasses_limit_with_no_server_verification(
    client, respx_mock, device_id
):
    """Same gap as chat.py, documented separately here because scan.py
    enforces it independently (its own rate limiter, its own is_pro
    check) — Work Item C needs to close both call sites, not just one.
    """
    respx_mock.post(ANTHROPIC_URL).mock(return_value=_anthropic_vision_reply())
    body = {
        "image_base64": FAKE_IMAGE_BASE64,
        "device_id": device_id,
        "is_pro": True,
    }
    for _ in range(7):  # comfortably more than the free limit of 5
        res = client.post("/api/v1/scan/receipt", json=body)
        assert res.status_code == 200


def test_scan_receipt_invalid_media_type_rejected_before_any_network_call(
    client, respx_mock
):
    res = client.post(
        "/api/v1/scan/receipt",
        json={
            "image_base64": FAKE_IMAGE_BASE64,
            "media_type": "image/bmp",
            "is_pro": True,
        },
    )
    assert res.status_code == 400
    # No route was registered on respx_mock for this test; if the code had
    # tried to reach Anthropic anyway, the test would fail via respx
    # rather than silently hitting the network.


def test_scan_receipt_missing_anthropic_key_fails_fast(client, respx_mock, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    res = client.post(
        "/api/v1/scan/receipt",
        json={"image_base64": FAKE_IMAGE_BASE64, "is_pro": True},
    )
    assert res.status_code == 500
