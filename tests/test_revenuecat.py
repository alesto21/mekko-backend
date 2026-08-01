"""Unit tests for app/services/revenuecat.py.

Endpoint-level integration tests (does chat.py/scan.py actually use this
correctly, including the forged is_pro + legacy-request cases) live in
test_chat.py and test_scan.py instead, since that's where the behavior
that actually matters to a caller is observable.
"""
import httpx
import pytest

from app.core.config import settings
from app.services import revenuecat

REVENUECAT_URL = "https://api.revenuecat.com/v1/subscribers/rc-user-1"


def _subscriber_body(entitlements: dict):
    return {"subscriber": {"entitlements": entitlements}}


@pytest.fixture(autouse=True)
def enable_verification(monkeypatch):
    monkeypatch.setattr(settings, "revenuecat_secret_key", "test-revenuecat-secret")


def test_verification_enabled_reflects_secret_key_presence(monkeypatch):
    monkeypatch.setattr(settings, "revenuecat_secret_key", "some-key")
    assert revenuecat.verification_enabled() is True
    monkeypatch.setattr(settings, "revenuecat_secret_key", "")
    assert revenuecat.verification_enabled() is False


async def test_active_lifetime_entitlement_is_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=_subscriber_body(
                {"pro_access": {"expires_date": None, "grace_period_expires_date": None}}
            ),
        )
    )
    assert await revenuecat.verify_entitlement("rc-user-1") is True


async def test_active_future_expiry_is_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=_subscriber_body(
                {
                    "pro_access": {
                        "expires_date": "2999-01-01T00:00:00Z",
                        "grace_period_expires_date": None,
                    }
                }
            ),
        )
    )
    assert await revenuecat.verify_entitlement("rc-user-1") is True


async def test_expired_with_no_grace_period_is_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=_subscriber_body(
                {
                    "pro_access": {
                        "expires_date": "2000-01-01T00:00:00Z",
                        "grace_period_expires_date": None,
                    }
                }
            ),
        )
    )
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_expired_but_within_grace_period_is_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=_subscriber_body(
                {
                    "pro_access": {
                        "expires_date": "2000-01-01T00:00:00Z",
                        "grace_period_expires_date": "2999-01-01T00:00:00Z",
                    }
                }
            ),
        )
    )
    assert await revenuecat.verify_entitlement("rc-user-1") is True


async def test_no_purchase_history_is_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(200, json=_subscriber_body({}))
    )
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_outage_network_error_treated_as_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(side_effect=httpx.ConnectError("boom"))
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_outage_timeout_treated_as_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(side_effect=httpx.TimeoutException("boom"))
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_unexpected_status_treated_as_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(return_value=httpx.Response(500))
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_malformed_response_treated_as_not_active(respx_mock):
    respx_mock.get(REVENUECAT_URL).mock(return_value=httpx.Response(200, json={"oops": True}))
    assert await revenuecat.verify_entitlement("rc-user-1") is False


async def test_result_is_cached_within_ttl(respx_mock, monkeypatch):
    fake_time = {"now": 1000.0}
    monkeypatch.setattr(revenuecat.time, "monotonic", lambda: fake_time["now"])
    monkeypatch.setattr(settings, "revenuecat_verification_cache_ttl_seconds", 60)

    route = respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200, json=_subscriber_body({"pro_access": {"expires_date": None}})
        )
    )

    assert await revenuecat.verify_entitlement("rc-user-1") is True
    fake_time["now"] += 30  # still within the 60s TTL
    assert await revenuecat.verify_entitlement("rc-user-1") is True
    assert route.call_count == 1  # second call served from cache


async def test_cache_expires_after_ttl(respx_mock, monkeypatch):
    fake_time = {"now": 1000.0}
    monkeypatch.setattr(revenuecat.time, "monotonic", lambda: fake_time["now"])
    monkeypatch.setattr(settings, "revenuecat_verification_cache_ttl_seconds", 60)

    route = respx_mock.get(REVENUECAT_URL).mock(
        return_value=httpx.Response(
            200, json=_subscriber_body({"pro_access": {"expires_date": None}})
        )
    )

    assert await revenuecat.verify_entitlement("rc-user-1") is True
    fake_time["now"] += 61  # past the TTL
    assert await revenuecat.verify_entitlement("rc-user-1") is True
    assert route.call_count == 2  # re-fetched after expiry
