"""Shared pytest fixtures for the backend test suite.

Two safety properties this file guarantees for every test in the suite,
by design, not by convention:

1. No test ever depends on the real .env file. Every external-service API
   key is forced to a fake, non-empty placeholder by an autouse fixture,
   so test behavior is identical on a developer's machine (which has a
   real .env with real production keys) and in CI (which has none).
   Tests that specifically want to exercise the "key not configured" path
   override a key back to "" explicitly within that test.

2. No test can make a real outbound network call. `respx_mock` is
   activated for every test via an autouse fixture, and respx's default
   behavior is to raise if a request doesn't match a registered route —
   so an accidentally-unmocked call fails the test loudly instead of
   silently reaching the network.
"""
import uuid

import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import tecdoc


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def device_id() -> str:
    """A fresh, unique device_id per test.

    The rate limiters (`chat_rate_limiter`, `scan_rate_limiter`) are
    module-level singletons that hold in-memory counts per device_id for
    the lifetime of the test process — exactly like they do in production
    between deploys. Reusing a fixed device_id across tests would leak
    rate-limit state between them and make results depend on test order.
    A unique id per test sidesteps that without reaching into the
    limiter's private internals.
    """
    return f"test-{uuid.uuid4()}"


@pytest.fixture(autouse=True)
def fake_api_keys(monkeypatch):
    """Force all external API keys to fake, non-empty values by default.

    Important nuance discovered while writing these tests: this only
    actually reaches `anthropic_chat.py` / `anthropic_vision.py`, which
    read `settings.anthropic_api_key` fresh on every call. It has NO
    effect on `VegvesenetClient` or `TecDocClient` — both read their key
    out of `settings` exactly once, at import time, into an instance
    attribute (`vegvesenet.py:9-11`, `tecdoc.py:63-68`). Patching
    `settings` after that point doesn't change what those singletons
    already captured. Tests exercising the "key missing" path for those
    two services patch the singleton's own attribute directly instead —
    see test_cars.py::test_lookup_car_missing_api_key and
    test_parts.py::test_resolve_missing_rapidapi_key.

    This is harmless for every other test here (respx blocks the real
    call regardless of what's in the request headers), but it does mean
    the real .env key for Vegvesen/TecDoc — if present on the machine
    running the tests — is technically what gets baked into those
    intercepted requests, not this fixture's fake value. Worth knowing if
    someone ever adds a test that inspects outgoing request headers.

    Individual tests that need to test the "key missing" behavior should
    monkeypatch the relevant field back to "" themselves.
    """
    monkeypatch.setattr(settings, "vegvesenet_api_key", "test-vegvesenet-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    monkeypatch.setattr(settings, "rapidapi_key", "test-rapidapi-key")
    return settings


@pytest.fixture(autouse=True)
def clear_tecdoc_cache():
    """`tecdoc.py` caches every RapidAPI response in a module-level dict,
    keyed only by request path, for the lifetime of the process — exactly
    like it does in production between deploys. Without clearing it, a
    test that mocks a given path would leak its cached response into a
    later test that mocks the same path with different data, making
    results depend on test order.
    """
    tecdoc._cache.clear()
    yield
    tecdoc._cache.clear()


@pytest.fixture(autouse=True)
def respx_mock():
    """Block all real outbound HTTP for every test; tests register the
    specific routes they expect via this fixture's yielded router.
    """
    with respx.mock(assert_all_called=False) as mock_router:
        yield mock_router
