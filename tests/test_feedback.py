"""Baseline behavior for POST /api/v1/feedback (app/api/v1/endpoints/feedback.py).

Mocks the optional Discord webhook call.
"""
import httpx

from app.core.config import settings


def test_submit_feedback_without_webhook_configured(client, respx_mock, monkeypatch):
    monkeypatch.setattr(settings, "discord_webhook_url", "")
    res = client.post(
        "/api/v1/feedback",
        json={"message": "Appen krasjet når jeg åpnet garasjen."},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    # No route registered on respx_mock: if the code tried to call Discord
    # anyway despite no URL being configured, this test would fail via
    # respx rather than silently making a real request.


def test_submit_feedback_with_webhook_configured(client, respx_mock, monkeypatch):
    webhook_url = "https://discord.com/api/webhooks/test/token"
    monkeypatch.setattr(settings, "discord_webhook_url", webhook_url)
    route = respx_mock.post(webhook_url).mock(return_value=httpx.Response(204))

    res = client.post(
        "/api/v1/feedback",
        json={
            "message": "Kan dere legge til Android-støtte?",
            "subject": "Forslag",
            "contact_email": "test@example.com",
        },
    )
    assert res.status_code == 200
    assert route.called


def test_submit_feedback_discord_failure_does_not_fail_the_request(
    client, respx_mock, monkeypatch
):
    """Documents today's deliberate behavior (feedback.py wraps the Discord
    call in a bare try/except): a broken webhook must not take down the
    user-facing feedback flow.
    """
    webhook_url = "https://discord.com/api/webhooks/test/token"
    monkeypatch.setattr(settings, "discord_webhook_url", webhook_url)
    respx_mock.post(webhook_url).mock(side_effect=httpx.ConnectError("boom"))

    res = client.post(
        "/api/v1/feedback",
        json={"message": "test"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_submit_feedback_missing_message_is_rejected(client, respx_mock):
    res = client.post("/api/v1/feedback", json={"message": ""})
    assert res.status_code == 422
