"""Baseline behavior for GET /api/v1/cars/lookup (app/services/vegvesenet.py).

Mocks the outbound call to Statens Vegvesen's Kjøretøyopplysninger API.
"""
import httpx

from app.core.config import settings

VEGVESEN_SUCCESS_BODY = {
    "kjoretoydataListe": [
        {
            "kjoretoyId": {
                "kjennemerke": "AB12345",
                "understellsnummer": "VF1TESTVIN0000001",
            },
            "godkjenning": {
                "tekniskGodkjenning": {
                    "tekniskeData": {
                        "generelt": {
                            "merke": [{"merke": "TOYOTA"}],
                            "handelsbetegnelse": ["COROLLA"],
                        },
                        "motorOgDrivverk": {
                            "motor": [
                                {
                                    "slagvolum": 1800,
                                    "drivstoff": [
                                        {
                                            "drivstoffKode": {"kodeNavn": "Bensin"},
                                            "maksNettoEffekt": 90,
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                }
            },
            "forstegangsregistrering": {
                "registrertForstegangNorgeDato": "2018-05-01"
            },
        }
    ]
}


def test_lookup_car_success(client, respx_mock):
    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=VEGVESEN_SUCCESS_BODY)
    )
    res = client.get("/api/v1/cars/lookup", params={"plate": "AB12345"})
    assert res.status_code == 200
    # Today's behavior: the endpoint passes the raw Vegvesen JSON straight
    # through, unparsed. Documenting this because it's easy to assume the
    # response is already normalized when it isn't.
    assert res.json() == VEGVESEN_SUCCESS_BODY


def test_lookup_car_not_found(client, respx_mock):
    respx_mock.get(settings.vegvesenet_base_url).mock(return_value=httpx.Response(404))
    res = client.get("/api/v1/cars/lookup", params={"plate": "ZZ99999"})
    assert res.status_code == 404


def test_lookup_car_upstream_error(client, respx_mock):
    respx_mock.get(settings.vegvesenet_base_url).mock(return_value=httpx.Response(500))
    res = client.get("/api/v1/cars/lookup", params={"plate": "AB12345"})
    assert res.status_code == 500


def test_lookup_car_missing_api_key(client, respx_mock, monkeypatch):
    # VegvesenetClient reads settings.vegvesenet_api_key exactly once, at
    # import time, into self.api_key (vegvesenet.py:9-11) — it does not
    # re-read `settings` on every call. So monkeypatching the settings
    # object here has no effect on the already-constructed singleton;
    # the guard this test is exercising checks `self.api_key`, so that's
    # what has to be patched to faithfully reproduce "key not configured".
    from app.services.vegvesenet import vegvesenet_client

    monkeypatch.setattr(vegvesenet_client, "api_key", "")
    res = client.get("/api/v1/cars/lookup", params={"plate": "AB12345"})
    assert res.status_code == 500
    # No route was registered for this test, so if the code tried to make
    # a real call instead of failing fast, respx would raise before we
    # even got here.


def test_lookup_car_plate_too_short(client, respx_mock):
    # Query validation (min_length=2) happens before any external call.
    res = client.get("/api/v1/cars/lookup", params={"plate": "A"})
    assert res.status_code == 422
