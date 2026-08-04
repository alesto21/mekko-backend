"""Baseline behavior for /api/v1/parts/* (app/services/tecdoc.py).

Mocks both outbound dependencies these endpoints chain through: Statens
Vegvesen (vehicle lookup) and the RapidAPI TecDoc mirror (fitment data).
"""
import httpx
import pytest

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
        "fuelType": "Bensin",  # real catalog spelling (Norwegian), confirmed live -- not "Petrol"
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


# ---------------------------------------------------------------------------
# Gate A -- manufacturer normalization (app/services/tecdoc.py::_match_manufacturer)
#
# The catalog's real 698-entry manufacturer list spells Volkswagen as exactly
# "VW" -- no entry contains the full word "VOLKSWAGEN" (confirmed against a
# real live response this session). Since "VW" and "VOLKSWAGEN" share no
# substring in either direction, the existing exact/partial matching alone
# can never resolve a real Vegvesen `merke` of "VOLKSWAGEN". These IDs mirror
# the real, live-confirmed catalog data for each brand.
# ---------------------------------------------------------------------------
from app.services.tecdoc import _match_manufacturer, _score_engine, _candidate_models  # noqa: E402

MANUFACTURERS_REAL_SHAPE = [
    {"manufacturerId": 121, "manufacturerName": "VW"},
    {"manufacturerId": 5, "manufacturerName": "AUDI"},
    {"manufacturerId": 16, "manufacturerName": "BMW"},
    {"manufacturerId": 74, "manufacturerName": "MERCEDES-BENZ"},
    {"manufacturerId": 106, "manufacturerName": "SKODA"},
    {"manufacturerId": 111, "manufacturerName": "TOYOTA"},
    {"manufacturerId": 183, "manufacturerName": "HYUNDAI"},
    # Regional joint-venture variants that share "VW" as a substring -- these
    # exist for real and must NOT be matched instead of the plain "VW" entry.
    {"manufacturerId": 8223, "manufacturerName": "VW (ANHUI)"},
    {"manufacturerId": 2859, "manufacturerName": "VW (FAW)"},
    {"manufacturerId": 3035, "manufacturerName": "VW (SVW)"},
]


def test_match_manufacturer_volkswagen_resolves_via_alias():
    result = _match_manufacturer("VOLKSWAGEN", MANUFACTURERS_REAL_SHAPE)
    assert result == {"manufacturerId": 121, "manufacturerName": "VW"}


def test_match_manufacturer_vw_exact_still_works_directly():
    """If Vegvesen ever sends "VW" directly, the pre-existing exact match
    path handles it without ever consulting the alias table."""
    result = _match_manufacturer("VW", MANUFACTURERS_REAL_SHAPE)
    assert result == {"manufacturerId": 121, "manufacturerName": "VW"}


@pytest.mark.parametrize(
    "merke,expected_name",
    [
        ("AUDI", "AUDI"),
        ("BMW", "BMW"),
        ("MERCEDES-BENZ", "MERCEDES-BENZ"),
        ("MERCEDES", "MERCEDES-BENZ"),  # partial-match fallback, already-working
        ("SKODA", "SKODA"),
        ("TOYOTA", "TOYOTA"),
        ("HYUNDAI", "HYUNDAI"),
    ],
)
def test_match_manufacturer_existing_brands_unaffected_by_alias_table(merke, expected_name):
    result = _match_manufacturer(merke, MANUFACTURERS_REAL_SHAPE)
    assert result is not None
    assert result["manufacturerName"] == expected_name


def test_resolve_volkswagen_end_to_end(client, respx_mock):
    """Full endpoint-level proof, not just the unit-level alias test above:
    a real Vegvesen response with merke="VOLKSWAGEN" must resolve through
    the actual /parts/resolve chain, not just in isolation."""
    vw_vegvesen_body = {
        "kjoretoydataListe": [
            {
                "kjoretoyId": {"kjennemerke": "EK12345", "understellsnummer": "WVW1"},
                "godkjenning": {
                    "tekniskGodkjenning": {
                        "tekniskeData": {
                            "generelt": {
                                "merke": [{"merke": "VOLKSWAGEN"}],
                                "handelsbetegnelse": ["GOLF VI"],
                            },
                            "motorOgDrivverk": {
                                "motor": [
                                    {
                                        "slagvolum": 1197,
                                        "drivstoff": [
                                            {
                                                "drivstoffKode": {"kodeNavn": "Bensin"},
                                                "maksNettoEffekt": 63,
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                },
                "forstegangsregistrering": {
                    "registrertForstegangNorgeDato": "2011-01-01"
                },
            }
        ]
    }
    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=vw_vegvesen_body)
    )
    respx_mock.get(MANUFACTURERS_URL).mock(
        return_value=httpx.Response(200, json=MANUFACTURERS_REAL_SHAPE)
    )
    models_url = (
        f"https://{TECDOC_HOST}/models/list/type-id/{TYPE_ID}"
        f"/manufacturer-id/121/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
    )
    respx_mock.get(models_url).mock(
        return_value=httpx.Response(
            200,
            json=[{"modelId": 7873, "modelName": "GOLF VI (5K1)",
                   "modelYearFrom": "2008", "modelYearTo": "2014"}],
        )
    )
    types_url = (
        f"https://{TECDOC_HOST}/types/type-id/{TYPE_ID}/list-vehicles-types/7873"
        f"/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
    )
    respx_mock.get(types_url).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "vehicleId": 9621, "modelName": "GOLF VI (5K1)",
                "typeEngineName": "1.2 TSI", "powerKw": 63, "capacityTech": 1197,
                "fuelType": "Bensin",
                "constructionIntervalStart": "2010-05", "constructionIntervalEnd": "2012-11",
                "engineCodes": "CBZA",
            }],
        )
    )
    res = client.get("/api/v1/parts/resolve", params={"plate": "EK12345"})
    assert res.status_code == 200
    body = res.json()
    assert body["vehicleId"] == 9621
    assert body["confident"] is True


# ---------------------------------------------------------------------------
# Gate A -- fuel normalization (app/services/tecdoc.py::_score_engine)
#
# The catalog's real `fuelType` for petrol cars is literally "Bensin"
# (Norwegian, confirmed live on a real Golf VI CBZA variant) -- not
# "Petrol" (English). Diesel matching only ever worked by coincidence
# (spelled the same in both languages).
# ---------------------------------------------------------------------------

def test_score_engine_fuel_bonus_fires_for_real_bensin_spelling():
    engine = {
        "powerKw": 63, "capacityTech": 1197, "fuelType": "Bensin",
        "constructionIntervalStart": "2010-05", "constructionIntervalEnd": "2012-11",
    }
    with_fuel = _score_engine(engine, slagvolum=1197, kw=63, fuel="Bensin", year=2011)
    without_fuel_signal = _score_engine(engine, slagvolum=1197, kw=63, fuel=None, year=2011)
    assert with_fuel == without_fuel_signal + 30


def test_score_engine_diesel_still_matches():
    engine = {
        "powerKw": 130, "capacityTech": 1968, "fuelType": "Diesel",
        "constructionIntervalStart": "2011-03", "constructionIntervalEnd": "2018-09",
    }
    with_fuel = _score_engine(engine, slagvolum=1968, kw=130, fuel="Diesel", year=2015)
    without_fuel_signal = _score_engine(engine, slagvolum=1968, kw=130, fuel=None, year=2015)
    assert with_fuel == without_fuel_signal + 30


def test_score_engine_electric_synonym():
    engine = {
        "powerKw": 100, "capacityTech": 0, "fuelType": "Electric",
        "constructionIntervalStart": "2018-01", "constructionIntervalEnd": "2023-12",
    }
    with_fuel = _score_engine(engine, slagvolum=None, kw=100, fuel="Elektrisk", year=2020)
    without_fuel_signal = _score_engine(engine, slagvolum=None, kw=100, fuel=None, year=2020)
    assert with_fuel == without_fuel_signal + 30


def test_score_engine_mismatched_fuel_gets_no_bonus():
    engine = {
        "powerKw": 63, "capacityTech": 1197, "fuelType": "Diesel",
        "constructionIntervalStart": "2010-05", "constructionIntervalEnd": "2012-11",
    }
    with_fuel = _score_engine(engine, slagvolum=1197, kw=63, fuel="Bensin", year=2011)
    without_fuel_signal = _score_engine(engine, slagvolum=1197, kw=63, fuel=None, year=2011)
    assert with_fuel == without_fuel_signal


# ---------------------------------------------------------------------------
# Gate A -- safer vehicle resolution (_candidate_models, resolve_vehicle)
#
# Reproduces the real Golf VI (5K1) vs Golf Plus V (5M1, 521) ambiguity:
# both share the CBZA 1.2 TSI engine with near-identical specs. When
# Vegvesen's model name is specific ("GOLF VI"), resolution must be both
# confident and correct. When it's generic ("GOLF"), both models are
# legitimately plausible and confidence must correctly stay low -- this is
# real ambiguity in the data, not a bug to hide.
# ---------------------------------------------------------------------------

MODELS_GOLF_FAMILY = [
    {"modelId": 7873, "modelName": "GOLF VI (5K1)",
     "modelYearFrom": "2008", "modelYearTo": "2014"},
    {"modelId": 5379, "modelName": "GOLF PLUS V (5M1, 521)",
     "modelYearFrom": "2005", "modelYearTo": "2014"},
    {"modelId": 8442, "modelName": "GOLF VI Variant (AJ5)",
     "modelYearFrom": "2009", "modelYearTo": "2013"},
]

GOLF_VI_ENGINE = {
    "vehicleId": 9621, "modelName": "GOLF VI (5K1)", "typeEngineName": "1.2 TSI",
    "powerKw": 63, "capacityTech": 1197, "fuelType": "Bensin",
    "constructionIntervalStart": "2010-05", "constructionIntervalEnd": "2012-11",
    "engineCodes": "CBZA",
}
GOLF_PLUS_ENGINE = {
    "vehicleId": 7752, "modelName": "GOLF PLUS V (5M1, 521)", "typeEngineName": "1.2 TSI",
    "powerKw": 63, "capacityTech": 1197, "fuelType": "Bensin",
    "constructionIntervalStart": "2010-05", "constructionIntervalEnd": "2013-12",
    "engineCodes": "CBZA",
}


def test_candidate_models_exact_tier_excludes_golf_plus_and_variant():
    cands = _candidate_models("GOLF VI", "VOLKSWAGEN", None, MODELS_GOLF_FAMILY)
    assert {m["modelId"] for m in cands} == {7873}


def test_candidate_models_generic_golf_falls_back_to_broad_tier():
    """Unchanged behavior for the genuinely-ambiguous case: Vegvesen gives no
    generation, so every real Golf-family model stays a legitimate candidate."""
    cands = _candidate_models("GOLF", "VOLKSWAGEN", None, MODELS_GOLF_FAMILY)
    assert {m["modelId"] for m in cands} == {7873, 5379, 8442}


def _mock_golf_resolve_chain(respx_mock, vegvesen_modell: str):
    vegvesen_body = {
        "kjoretoydataListe": [
            {
                "kjoretoyId": {"kjennemerke": "EK12345", "understellsnummer": "WVW1"},
                "godkjenning": {
                    "tekniskGodkjenning": {
                        "tekniskeData": {
                            "generelt": {
                                "merke": [{"merke": "VOLKSWAGEN"}],
                                "handelsbetegnelse": [vegvesen_modell],
                            },
                            "motorOgDrivverk": {
                                "motor": [{
                                    "slagvolum": 1197,
                                    "drivstoff": [{
                                        "drivstoffKode": {"kodeNavn": "Bensin"},
                                        "maksNettoEffekt": 63,
                                    }],
                                }]
                            },
                        }
                    }
                },
                "forstegangsregistrering": {"registrertForstegangNorgeDato": "2011-01-01"},
            }
        ]
    }
    respx_mock.get(settings.vegvesenet_base_url).mock(
        return_value=httpx.Response(200, json=vegvesen_body)
    )
    respx_mock.get(MANUFACTURERS_URL).mock(
        return_value=httpx.Response(200, json=MANUFACTURERS_REAL_SHAPE)
    )
    models_url = (
        f"https://{TECDOC_HOST}/models/list/type-id/{TYPE_ID}"
        f"/manufacturer-id/121/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
    )
    respx_mock.get(models_url).mock(
        return_value=httpx.Response(200, json=MODELS_GOLF_FAMILY)
    )
    for model_id, engine in ((7873, GOLF_VI_ENGINE), (5379, GOLF_PLUS_ENGINE), (8442, None)):
        types_url = (
            f"https://{TECDOC_HOST}/types/type-id/{TYPE_ID}/list-vehicles-types/{model_id}"
            f"/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
        )
        respx_mock.get(types_url).mock(
            return_value=httpx.Response(200, json=[engine] if engine else [])
        )


def test_resolve_specific_model_name_is_confident_and_correct(client, respx_mock):
    _mock_golf_resolve_chain(respx_mock, "GOLF VI")
    res = client.get("/api/v1/parts/resolve", params={"plate": "EK12345"})
    assert res.status_code == 200
    body = res.json()
    assert body["confident"] is True
    assert body["vehicleId"] == 9621


def test_resolve_generic_model_name_stays_ambiguous_but_prefers_plain_model(client, respx_mock):
    _mock_golf_resolve_chain(respx_mock, "GOLF")
    res = client.get("/api/v1/parts/resolve", params={"plate": "EK12345"})
    assert res.status_code == 200
    body = res.json()
    assert body["confident"] is False
    assert body["vehicleId"] == 9621  # tie-break prefers the shorter/plainer model name
    candidate_ids = {c["vehicleId"] for c in body["candidates"]}
    assert {9621, 7752} <= candidate_ids


# ---------------------------------------------------------------------------
# Gate B -- technical specifications (app/services/tecdoc.py::specifications_for_article,
# GET /api/v1/parts/articles/{article_id}/specifications)
#
# Real shape confirmed live this session on a Bosch oil filter for the
# correct Golf VI vehicle: a flat JSON array of {"criteriaName", "criteriaValue"}
# objects, no envelope. This fixture mirrors that exact shape and includes
# real field names observed (including "for OE-nummer" -- OEM numbers are
# genuinely present here, and "Motorkode"/"Årsmodell fra"/"til" -- fitment
# restriction data, not just physical dimensions).
# ---------------------------------------------------------------------------

SPECIFICATIONS_REAL_SHAPE = [
    {"criteriaName": "Filtertype", "criteriaValue": "Påskruingsfilter"},
    {"criteriaName": "Gjengemål", "criteriaValue": "3/4\"\" 16 UNF-2B"},
    {"criteriaName": "Høyde [mm]", "criteriaValue": "93"},
    {"criteriaName": "for OE-nummer", "criteriaValue": "03C 115 561 D; 03C 115 561 H"},
    {"criteriaName": "Motorkode", "criteriaValue": "CLSC; CNWB<D31/TF0>"},
]

SPECIFICATIONS_URL = (
    f"https://{TECDOC_HOST}/articles/selection-of-all-specifications-criterias-for-the-article"
    f"/article-id/6926974/lang-id/{LANG_ID}/country-filter-id/{COUNTRY_ID}"
)


def test_specifications_happy_path(client, respx_mock):
    respx_mock.get(SPECIFICATIONS_URL).mock(
        return_value=httpx.Response(200, json=SPECIFICATIONS_REAL_SHAPE)
    )
    res = client.get("/api/v1/parts/articles/6926974/specifications")
    assert res.status_code == 200
    body = res.json()
    assert body["articleId"] == 6926974
    assert body["specifications"] == [
        {"label": "Filtertype", "value": "Påskruingsfilter"},
        {"label": "Gjengemål", "value": "3/4\"\" 16 UNF-2B"},
        {"label": "Høyde [mm]", "value": "93"},
        {"label": "for OE-nummer", "value": "03C 115 561 D; 03C 115 561 H"},
        {"label": "Motorkode", "value": "CLSC; CNWB<D31/TF0>"},
    ]


def test_specifications_cached_second_call_hits_network_once(client, respx_mock):
    route = respx_mock.get(SPECIFICATIONS_URL).mock(
        return_value=httpx.Response(200, json=SPECIFICATIONS_REAL_SHAPE)
    )
    first = client.get("/api/v1/parts/articles/6926974/specifications")
    second = client.get("/api/v1/parts/articles/6926974/specifications")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert route.call_count == 1


def test_specifications_empty_response_is_not_an_error(client, respx_mock):
    respx_mock.get(SPECIFICATIONS_URL).mock(return_value=httpx.Response(200, json=[]))
    res = client.get("/api/v1/parts/articles/6926974/specifications")
    assert res.status_code == 200
    assert res.json() == {"articleId": 6926974, "specifications": []}


def test_specifications_malformed_entries_are_filtered_not_exposed_raw(client, respx_mock):
    """Normalize inconsistent/partial data in the backend rather than
    exposing raw API irregularities to Flutter, per the Gate B instruction."""
    respx_mock.get(SPECIFICATIONS_URL).mock(
        return_value=httpx.Response(200, json=[
            {"criteriaName": "Filtertype", "criteriaValue": "Påskruingsfilter"},
            {"criteriaName": "Tom verdi", "criteriaValue": ""},
            {"criteriaName": "Manglende verdi"},
            {"criteriaValue": "Mangler navn"},
            "ikke engang et objekt",
            {"criteriaName": None, "criteriaValue": "null-navn"},
        ])
    )
    res = client.get("/api/v1/parts/articles/6926974/specifications")
    assert res.status_code == 200
    assert res.json()["specifications"] == [
        {"label": "Filtertype", "value": "Påskruingsfilter"},
    ]


def test_specifications_missing_rapidapi_key(client, respx_mock, monkeypatch):
    from app.services.tecdoc import client as tecdoc_client
    monkeypatch.setattr(tecdoc_client, "key", "")
    res = client.get("/api/v1/parts/articles/6926974/specifications")
    assert res.status_code == 500
