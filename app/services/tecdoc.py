"""TecDoc-katalog via RapidAPI ("auto-parts-catalog").

Gir fitment-data: hvilke reservedeler som passer en konkret bil. TecDoc har
INGEN priser — pris/kjøp håndteres via affiliate-lenker (se shop_links).

Kjeden:
  Vegvesen-bil (merke, modell, slagvolum, effekt, drivstoff, år)
    -> manufacturerId -> modelId -> vehicleId (motorvariant)
    -> kategorier -> artikler (deler som passer)

Resultater caches i minne for å spare RapidAPI-kvote (gratis = 100 kall/mnd).
"""
import re
from urllib.parse import quote_plus

import httpx
from fastapi import HTTPException

from app.core.config import settings

# App-kategori (samme id-er som _partCategories i Flutter-appen) -> TecDoc
# productGroup-id-er. En app-kategori kan dekke flere TecDoc-grupper.
CATEGORY_MAP: dict[str, list[int]] = {
    "olje":           [100470],          # Oljefilter
    "luftfilter":     [100260],          # Luftfilter
    "pollenfilter":   [100346],          # Kupéfilter
    "drivstoffilter": [100261],          # Drivstoffilter
    "bremser":        [100030, 100032],  # Bremseklosser + bremseskiver
    "bremsevaeske":   [102208],          # Bremsevæske
    "viskere":        [100133],          # Vindusviskere
    "tennplugger":    [100151],          # Tennplugger
    "tennspoler":     [100150],          # Tennspoler
    "tannreim":       [103278, 100091],  # Registerreim-kit + vannpumpe
    "stotdempere":    [100121, 100113],  # Støtdempere + spiralfjærer
    "stabilisator":   [100573, 100571],  # Stabilisatorstag + bærearmer
    "hjullager":      [100579, 100062],  # Hjullager + drivaksel
    "clutch":         [100051],          # Clutch-kit
    "batteri":        [100042],          # Batteri
    "parer":          [100427, 100503],  # Pærer (hovedlys + generelt)
    "eksos":          [100046, 100793],  # Eksosanlegg + lambdasonde
    # spylervaeske, dekk, felger = universelle/ikke-fitment -> ikke via TecDoc
}

# Vegvesen drivstoff -> TecDoc fuelType (delstreng-match, lowercase)
_FUEL_MAP = {
    "bensin": "petrol",
    "diesel": "diesel",
    "elektrisk": "electric",
    "el": "electric",
    "hybrid": "petrol",   # ofte ført som petrol/hybrid i TecDoc
}

_IMG_BASE = "https://fsn1.your-objectstorage.com/tecdoc2025/media_files/images/"
_cache: dict[str, object] = {}


def _norm(s: str | None) -> str:
    """Normaliser for sammenligning: store bokstaver, fjern mellomrom/bindestrek."""
    return re.sub(r"[\s\-]", "", (s or "").upper())


class TecDocClient:
    def __init__(self) -> None:
        self.host = settings.rapidapi_host
        self.key = settings.rapidapi_key
        self.lang = settings.tecdoc_lang_id
        self.country = settings.tecdoc_country_id
        self.type_id = settings.tecdoc_type_id

    async def _get(self, path: str) -> object:
        if not self.key:
            raise HTTPException(
                status_code=500, detail="RAPIDAPI_KEY mangler i miljøvariabler"
            )
        if path in _cache:
            return _cache[path]
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                res = await client.get(
                    f"https://{self.host}{path}",
                    headers={
                        "x-rapidapi-key": self.key,
                        "x-rapidapi-host": self.host,
                    },
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=503, detail=f"Klarte ikke kontakte TecDoc: {exc}"
                ) from exc
        if res.status_code != 200:
            raise HTTPException(
                status_code=res.status_code,
                detail=f"TecDoc returnerte {res.status_code} for {path}",
            )
        data = res.json()
        _cache[path] = data
        return data

    async def manufacturers(self) -> list[dict]:
        d = await self._get(f"/manufacturers/list/type-id/{self.type_id}")
        return d if isinstance(d, list) else d.get("manufacturers", [])

    async def models(self, manufacturer_id: int) -> list[dict]:
        d = await self._get(
            f"/models/list/type-id/{self.type_id}"
            f"/manufacturer-id/{manufacturer_id}"
            f"/lang-id/{self.lang}/country-filter-id/{self.country}"
        )
        return d if isinstance(d, list) else _first_list(d)

    async def engine_types(self, model_id: int) -> list[dict]:
        d = await self._get(
            f"/types/type-id/{self.type_id}/list-vehicles-types/{model_id}"
            f"/lang-id/{self.lang}/country-filter-id/{self.country}"
        )
        return d if isinstance(d, list) else _first_list(d)

    async def categories(self, vehicle_id: int) -> dict:
        d = await self._get(
            f"/category/type-id/{self.type_id}"
            f"/products-groups-variant-3/{vehicle_id}/lang-id/{self.lang}"
        )
        return d.get("categories", {}) if isinstance(d, dict) else {}

    async def articles(self, vehicle_id: int, category_id: int) -> list[dict]:
        d = await self._get(
            f"/articles/list/type-id/{self.type_id}"
            f"/vehicle-id/{vehicle_id}/category-id/{category_id}/lang-id/{self.lang}"
        )
        return d.get("articles", []) if isinstance(d, dict) else []


def _first_list(d: dict) -> list:
    for v in d.values():
        if isinstance(v, list):
            return v
    return []


client = TecDocClient()


# ---------------------------------------------------------------------------
# Matching: Vegvesen-bil -> TecDoc vehicleId
# ---------------------------------------------------------------------------
def _year(vehicle: dict) -> int | None:
    fr = vehicle.get("forsteRegistrert")
    if isinstance(fr, str) and len(fr) >= 4 and fr[:4].isdigit():
        return int(fr[:4])
    return vehicle.get("aarsmodell")


def _match_manufacturer(merke: str, mfrs: list[dict]) -> dict | None:
    target = _norm(merke)
    if not target:
        return None
    exact = [m for m in mfrs if _norm(m.get("manufacturerName")) == target]
    if exact:
        return exact[0]
    # delstreng (f.eks. "VW" / "VOLKSWAGEN"), foretrekk korteste navn
    partial = [
        m for m in mfrs
        if target in _norm(m.get("manufacturerName"))
        or _norm(m.get("manufacturerName")) in target
    ]
    partial.sort(key=lambda m: len(m.get("manufacturerName", "")))
    return partial[0] if partial else None


def _candidate_models(modell: str, merke: str, year: int | None,
                      models: list[dict]) -> list[dict]:
    mod = _norm(modell)
    mrk = _norm(merke)
    if mod.startswith(mrk):           # "HYUNDAI I20" -> "I20"
        mod = mod[len(mrk):]
    out = []
    for m in models:
        name = _norm(m.get("modelName"))
        if not (mod and (mod in name or name.startswith(mod))):
            continue
        if year:
            yf = (m.get("modelYearFrom") or "0000")[:4]
            yt = (m.get("modelYearTo") or "9999")[:4]
            if not (yf.isdigit() and int(yf) <= year and
                    (not yt.isdigit() or year <= int(yt))):
                continue
        out.append(m)
    return out


def _score_engine(e: dict, slagvolum: int | None, kw: float | None,
                  fuel: str | None, year: int | None) -> int:
    score = 0
    try:
        ekw = float(e.get("powerKw") or 0)
    except (TypeError, ValueError):
        ekw = 0
    if kw and ekw:
        if round(ekw) == round(kw):
            score += 100
        elif abs(ekw - kw) <= 2:
            score += 60
    try:
        cc = int(float(e.get("capacityTech") or 0))
    except (TypeError, ValueError):
        cc = 0
    if slagvolum and cc:
        if abs(cc - slagvolum) <= 15:
            score += 50
        elif abs(cc - slagvolum) <= 40:
            score += 20
    if fuel:
        want = _FUEL_MAP.get((fuel or "").strip().lower(), "")
        if want and want in (e.get("fuelType") or "").lower():
            score += 30
    if year:
        sf = (e.get("constructionIntervalStart") or "0000")[:4]
        st = (e.get("constructionIntervalEnd") or "9999")[:4]
        if sf.isdigit() and int(sf) <= year and (not st.isdigit() or year <= int(st)):
            score += 20
    return score


def _engine_brief(e: dict) -> dict:
    return {
        "vehicleId": e.get("vehicleId"),
        "name": f"{e.get('modelName', '')} {e.get('typeEngineName', '')}".strip(),
        "powerKw": e.get("powerKw"),
        "powerPs": e.get("powerPs"),
        "capacity": e.get("capacityTech"),
        "fuel": e.get("fuelType"),
        "years": f"{(e.get('constructionIntervalStart') or '')[:4]}–"
                 f"{(e.get('constructionIntervalEnd') or '')[:4] or 'd.d.'}",
        "engineCodes": e.get("engineCodes"),
    }


async def resolve_vehicle(vehicle: dict) -> dict:
    """Match en Vegvesen-bil til en TecDoc vehicleId.

    Returnerer best treff + alternativer. `confident=False` betyr at appen
    bør be brukeren bekrefte motorvariant (flere like sannsynlige treff).
    """
    merke = vehicle.get("merke") or ""
    modell = vehicle.get("modell") or ""
    slagvolum = vehicle.get("slagvolum")
    kw = vehicle.get("effektKw")
    fuel = vehicle.get("drivstoff")
    year = _year(vehicle)

    mfr = _match_manufacturer(merke, await client.manufacturers())
    if not mfr:
        raise HTTPException(404, f"Fant ikke merket «{merke}» i TecDoc")

    models = await client.models(mfr["manufacturerId"])
    cands = _candidate_models(modell, merke, year, models)
    if not cands:                       # fall tilbake uten år-filter
        cands = _candidate_models(modell, merke, None, models)
    if not cands:
        raise HTTPException(404, f"Fant ingen modell «{modell}» for {merke} i TecDoc")

    scored: list[tuple[int, dict]] = []
    for m in cands:
        for e in await client.engine_types(m["modelId"]):
            scored.append((_score_engine(e, slagvolum, kw, fuel, year), e))
    if not scored:
        raise HTTPException(404, "Fant ingen motorvarianter i TecDoc")
    scored.sort(key=lambda t: t[0], reverse=True)

    best_score, best = scored[0]
    top = [e for s, e in scored if s >= best_score - 20][:6]
    confident = best_score >= 120 and (
        len(scored) == 1 or scored[1][0] <= best_score - 40
    )
    return {
        "vehicleId": best.get("vehicleId"),
        "match": _engine_brief(best),
        "confident": confident,
        "candidates": [_engine_brief(e) for e in top],
    }


# ---------------------------------------------------------------------------
# Kjøp: affiliate-lenker (deep-link søk på delenummer). Erstatt med ekte
# affiliate-parametre når programmene er godkjent.
# ---------------------------------------------------------------------------
def shop_links(article_no: str, brand: str) -> list[dict]:
    q = quote_plus(f"{brand} {article_no}".strip())
    return [
        {"shop": "Autodoc",
         "url": f"https://www.autodoc.co.no/sok?keyword={q}"},
        {"shop": "bildeler.no",
         "url": f"https://www.bildeler.no/sok?q={q}"},
        {"shop": "Mekonomen",
         "url": f"https://www.mekster.no/sok?q={q}"},
    ]


def _img(a: dict) -> str | None:
    if a.get("s3image"):
        return a["s3image"]
    if a.get("articleMediaFileName") and a.get("supplierId"):
        return f"{_IMG_BASE}{a['supplierId']}/{a['articleMediaFileName']}"
    return None


async def parts_for_category(vehicle_id: int, app_category: str) -> list[dict]:
    """Hent alle artikler som passer bilen for en av appens 20 kategorier."""
    cat_ids = CATEGORY_MAP.get(app_category)
    if not cat_ids:
        raise HTTPException(404, f"Ukjent kategori «{app_category}»")
    seen: set[int] = set()
    out: list[dict] = []
    for cid in cat_ids:
        for a in await client.articles(vehicle_id, cid):
            aid = a.get("articleId")
            if aid in seen:
                continue
            seen.add(aid)
            out.append({
                "articleId": aid,
                "brand": a.get("supplierName"),
                "name": a.get("articleProductName"),
                "articleNo": a.get("articleNo"),
                "image": _img(a),
                "shops": shop_links(a.get("articleNo", ""), a.get("supplierName", "")),
            })
    return out


async def available_categories(vehicle_id: int) -> list[str]:
    """Hvilke av appens kategorier som finnes i TecDoc-treet for denne bilen."""
    tree = await client.categories(vehicle_id)
    present: set[str] = set()

    def walk(node: dict) -> None:
        for cid, info in node.items():
            try:
                present.add(int(cid))
            except (TypeError, ValueError):
                pass
            if info.get("children"):
                walk(info["children"])

    walk(tree)
    return [
        app_cat for app_cat, ids in CATEGORY_MAP.items()
        if any(i in present for i in ids)
    ]
