"""Baseline behavior for the root/health endpoints (app/main.py).

No external calls involved — these just confirm the app boots and the
two liveness endpoints Railway/anyone else would poll respond as today.
"""
from app.core.config import settings


def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json() == {"name": settings.project_name, "status": "ok"}


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}
