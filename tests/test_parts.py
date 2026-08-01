"""Baseline behavior for /api/v1/parts/* (app/services/tecdoc.py).

Mocks both outbound dependencies these endpoints chain through: Statens
Vegvesen (vehicle lookup) and the RapidAPI TecDoc mirror (fitment data).
"""
import httpx

from app.core.config import settings

VEGVESEN_BODY = {
    "kjoretoydataListe": [
        {
            "kjoretoyId": {"kjennemerke": "AB12345", "understellsnummer": "VF1X"},
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

TECDOC_HOST = settings.rapidapi_host
TYPE_ID = settings.tecdoc_type_id
LANG_ID = settings.tecdoc_lang_id
COUNTRY_ID = settings.tecdoc_country_id

MANUFACTURERS_URL = f"https://{TECDOC_HOST}/manufacturers/list/type-id/{TYPE_ID}"
MODELS_URL = (
    f"https://{TECDOC_HOST}/models/list/type-id/{TYPE_ID}"
    f"/manufacturer-id/99/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
)
ENGINE_TYPES_URL = (
    f"https://{TECDOC_HOST}/types/type-id/{TYPE_ID}/list-vehicles-types/555"
    f"/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
)

MANUFACTURERS_BODY = [
    {"manufacturerId": 99, "manufacturerName": "TOYOTA"},
    {"manufacturerId": 5, "manufacturerName": "VOLVO"},
]
MODELS_BODY = [
    {"modelId": 555, "modelName": "COROLLA", "modelYearFrom": "2013", "modelYearTo": "2019"}
]
ENGINE_TYPES_BODY = [
    {
        "vehicleId": 7777,
        "modelName": "Corolla",
        "typeEngineName": "1.8 Valvematic",
        "powerKw": 90,
        "powerPs": 140,
        "capacityTech": 1798,
        "fuelType": "Petrol",
        "constructionIntervalStart": "2013-01",
        "constructionIntervalEnd": "2019-12",
        "engineCodes": "2ZR-FE",
    }
]


def _mock_resolve_chain(respx_mock):
    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=VEGVESEN_BODY)
    )
    respx_mock.get(MANUFACTURERS_URL).mock(
        return_value=httpx.Response(200, json=MANUFACTURERS_BODY)
    )
    respx_mock.get(MODELS_URL).mock(return_value=httpx.Response(200, json=MODELS_BODY))
    respx_mock.get(ENGINE_TYPES_URL).mock(
        return_value=httpx.Response(200, json=ENGINE_TYPES_BODY)
    )


def test_resolve_confident_match(client, respx_mock):
    _mock_resolve_chain(respx_mock)
    res = client.get("/api/v1/parts/resolve", params={"plate": "AB12345"})
    assert res.status_code == 200
    body = res.json()
    assert body["vehicleId"] == 7777
    assert body["confident"] is True
    assert body["match"]["vehicleId"] == 7777


def test_resolve_manufacturer_not_in_tecdoc(client, respx_mock):
    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=VEGVESEN_BODY)
    )
    respx_mock.get(MANUFACTURERS_URL).mock(
        return_value=httpx.Response(
            200, json=[{"manufacturerId": 5, "manufacturerName": "VOLVO"}]
        )
    )
    res = client.get("/api/v1/parts/resolve", params={"plate": "AB12345"})
    assert res.status_code == 404


def test_resolve_missing_rapidapi_key(client, respx_mock, monkeypatch):
    # Same pattern as VegvesenetClient (see test_cars.py::
    # test_lookup_car_missing_api_key): TecDocClient reads
    # settings.rapidapi_key exactly once, at import time, into self.key
    # (tecdoc.py:63-68). Patching `settings` here would have no effect on
    # the already-constructed singleton, so the singleton's own attribute
    # is what needs patching to faithfully reproduce "key not configured".
    from app.services.tecdoc import client as tecdoc_client

    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=VEGVESEN_BODY)
    )
    monkeypatch.setattr(tecdoc_client, "key", "")
    res = client.get("/api/v1/parts/resolve", params={"plate": "AB12345"})
    assert res.status_code == 500


def test_categories_for_vehicle(client, respx_mock):
    categories_url = (
        f"https://{TECDOC_HOST}/category/type-id/{TYPE_ID}"
        f"/products-groups-variant-3/7777/lang-id/{LANG_ID}"
    )
    respx_mock.get(categories_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": {
                    "100470": {"text": "Oljefilter"},  # maps to app category "olje"
                    "100030": {"text": "Bremseklosser"},  # maps to "bremser"
                    "999999": {"text": "Ukjent"},  # not in CATEGORY_MAP
                }
            },
        )
    )
    res = client.get("/api/v1/parts/vehicles/7777/categories")
    assert res.status_code == 200
    cats = set(res.json()["categories"])
    assert cats == {"olje", "bremser"}


def test_articles_for_category(client, respx_mock):
    # "olje" maps to a single TecDoc productGroup id: 100470
    articles_url = (
        f"https://{TECDOC_HOST}/articles/list/type-id/{TYPE_ID}"
        f"/vehicle-id/7777/category-id/100470/lang-id/{LANG_ID}"
    )
    respx_mock.get(articles_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "articleId": 42,
                        "supplierName": "Mann Filter",
                        "articleProductName": "Oljefilter",
                        "articleNo": "W712/75",
                    }
                ]
            },
        )
    )
    res = client.get("/api/v1/parts/vehicles/7777/category/olje")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    article = body["articles"][0]
    assert article["brand"] == "Mann Filter"
    assert article["articleNo"] == "W712/75"
    # Buy links are search-URL deep links today, not real offers — asserting
    # that explicitly so this doesn't quietly start looking like real
    # retailer data in a future diff.
    assert {s["shop"] for s in article["shops"]} == {"Sammenlign priser", "Autodoc"}


def test_articles_for_unknown_category_returns_404(client, respx_mock):
    res = client.get("/api/v1/parts/vehicles/7777/category/does-not-exist")
    assert res.status_code == 404
