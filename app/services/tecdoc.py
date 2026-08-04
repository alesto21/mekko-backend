"""TecDoc-katalog via RapidAPI ("auto-parts-catalog").

Gir fitment-data: hvilke reservedeler som passer en konkret bil. TecDoc har
INGEN priser — pris/kjøp håndteres via affiliate-lenker (se shop_links).

Kjeden:
  Vegvesen-bil (merke, modell, slagvolum, effekt, drivstoff, år)
    -> manufacturerId -> modelId -> vehicleId (motorvariant)
    -> kategorier -> artikler (deler som passer)

Resultater caches i minne for å spare RapidAPI-kvote (gratis = 100 kall/mnd).
"""
import logging
import re
from urllib.parse import quote_plus

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

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

# Vegvesen drivstoff -> mulige TecDoc fuelType-stavemåter (delstreng-match,
# lowercase). Katalogens ekte fuelType er ikke pålitelig engelsk -- bensin
# kommer f.eks. tilbake som "Bensin" (norsk), ikke "Petrol", bekreftet mot
# ekte data. Diesel har historisk "virket" bare fordi "Diesel" staves likt
# på begge språk, ikke fordi feltet faktisk er engelsk.
_FUEL_SYNONYMS = {
    "bensin": ("bensin", "petrol"),
    "diesel": ("diesel",),
    "elektrisk": ("electric", "elektrisk", "ev"),
    "el": ("electric", "elektrisk", "ev"),
    "hybrid": ("hybrid", "bensin", "petrol"),
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

    async def specifications(self, article_id: int) -> list[dict]:
        """Rå spesifikasjoner for en artikkel. Cachet av `_get()` som alt
        annet her -- path inkluderer article_id, så caching er alt per
        artikkel uten noe ekstra kode."""
        d = await self._get(
            f"/articles/selection-of-all-specifications-criterias-for-the-article"
            f"/article-id/{article_id}/lang-id/{self.lang}/country-filter-id/{self.country}"
        )
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return _first_list(d)
        return []


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


# Kjente merkenavn der Vegvesen og katalogen bruker helt ulike stavemåter
# uten felles delstreng (f.eks. "VOLKSWAGEN" vs. katalogens "VW" -- verken
# inneholder den andre, så delstreng-fallback under kan aldri finne den).
# Bekreftet mot ekte katalogdata 2026-08: katalogen har KUN "VW", ikke
# "VOLKSWAGEN" i noen form.
_MANUFACTURER_ALIASES: dict[str, str] = {
    "VOLKSWAGEN": "VW",
}
_MANUFACTURER_ALIASES_REVERSE = {v: k for k, v in _MANUFACTURER_ALIASES.items()}


def _match_manufacturer(merke: str, mfrs: list[dict]) -> dict | None:
    target = _norm(merke)
    if not target:
        return None

    # Prøv target selv og eventuelle kjente alias (begge retninger) mot
    # eksakt treff først, før vi faller tilbake til delstreng-matching.
    exact_candidates = {target}
    if target in _MANUFACTURER_ALIASES:
        exact_candidates.add(_norm(_MANUFACTURER_ALIASES[target]))
    if target in _MANUFACTURER_ALIASES_REVERSE:
        exact_candidates.add(_norm(_MANUFACTURER_ALIASES_REVERSE[target]))

    exact = [
        m for m in mfrs
        if _norm(m.get("manufacturerName")) in exact_candidates
    ]
    if exact:
        return exact[0]
    # delstreng (f.eks. "MERCEDES" / "MERCEDES-BENZ"), foretrekk korteste navn
    partial = [
        m for m in mfrs
        if target in _norm(m.get("manufacturerName"))
        or _norm(m.get("manufacturerName")) in target
    ]
    partial.sort(key=lambda m: len(m.get("manufacturerName", "")))
    return partial[0] if partial else None


def _base_name(name: str | None) -> str:
    """Fjern en avsluttende parentes med chassiskode, f.eks.
    "GOLF VI (5K1)" -> "GOLF VI". Brukes for eksakt-tier matching under."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def _year_matches(m: dict, year: int | None) -> bool:
    if not year:
        return True
    yf = (m.get("modelYearFrom") or "0000")[:4]
    yt = (m.get("modelYearTo") or "9999")[:4]
    return yf.isdigit() and int(yf) <= year and (not yt.isdigit() or year <= int(yt))


def _candidate_models(modell: str, merke: str, year: int | None,
                      models: list[dict]) -> list[dict]:
    mod = _norm(modell)
    mrk = _norm(merke)
    if mod.startswith(mrk):           # "HYUNDAI I20" -> "I20"
        mod = mod[len(mrk):]
    if not mod:
        return []

    # Tier 1: eksakt treff mot modellnavnet uten chassiskode-parentesen,
    # f.eks. target "GOLF VI" treffer "GOLF VI (5K1)" men IKKE "GOLF VI
    # Variant (AJ5)" eller "GOLF PLUS V (5M1, 521)". Brukes bare når
    # Vegvesen-modellnavnet er spesifikt nok til å være utvetydig alene.
    exact = [
        m for m in models
        if _norm(_base_name(m.get("modelName"))) == mod and _year_matches(m, year)
    ]
    if exact:
        return exact

    # Tier 2: eksisterende delstreng-fallback (uendret oppførsel) -- brukes
    # når Vegvesen-modellnavnet er generisk (f.eks. "GOLF") og flere ekte
    # modeller er reelt sett like sannsynlige.
    out = []
    for m in models:
        name = _norm(m.get("modelName"))
        if not (mod in name or name.startswith(mod)):
            continue
        if not _year_matches(m, year):
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
        wants = _FUEL_SYNONYMS.get((fuel or "").strip().lower(), ())
        fuel_lower = (e.get("fuelType") or "").lower()
        if wants and any(w in fuel_lower for w in wants):
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
        logger.info("resolve_vehicle: fant ikke merke=%r i TecDoc", merke)
        raise HTTPException(404, f"Fant ikke merket «{merke}» i TecDoc")
    logger.info(
        "resolve_vehicle: merke=%r -> manufacturerId=%s (%s)",
        merke, mfr["manufacturerId"], mfr["manufacturerName"],
    )

    models = await client.models(mfr["manufacturerId"])
    cands = _candidate_models(modell, merke, year, models)
    if not cands:                       # fall tilbake uten år-filter
        cands = _candidate_models(modell, merke, None, models)
    if not cands:
        logger.info(
            "resolve_vehicle: fant ingen modell for modell=%r merke=%r", modell, merke
        )
        raise HTTPException(404, f"Fant ingen modell «{modell}» for {merke} i TecDoc")

    scored: list[tuple[int, dict]] = []
    for m in cands:
        for e in await client.engine_types(m["modelId"]):
            scored.append((_score_engine(e, slagvolum, kw, fuel, year), e))
    if not scored:
        logger.info("resolve_vehicle: fant ingen motorvarianter for cands=%r",
                     [m.get("modelName") for m in cands])
        raise HTTPException(404, "Fant ingen motorvarianter i TecDoc")

    # Sorter på synkende score; ved eksakt likhet foretrekk det korteste/
    # enkleste modellnavnet som standardvalg (f.eks. "GOLF VI (5K1)" foran
    # "GOLF PLUS V (5M1, 521)") -- ren tie-break, endrer ikke `confident`.
    scored.sort(key=lambda t: (-t[0], len(t[1].get("modelName") or "")))

    best_score, best = scored[0]
    top = [e for s, e in scored if s >= best_score - 20][:6]
    confident = best_score >= 120 and (
        len(scored) == 1 or scored[1][0] <= best_score - 40
    )
    if confident:
        logger.info(
            "resolve_vehicle: confident match vehicleId=%s score=%s",
            best.get("vehicleId"), best_score,
        )
    else:
        rejected = [(s, e.get("vehicleId"), e.get("modelName")) for s, e in scored[1:6]]
        logger.info(
            "resolve_vehicle: NOT confident, default vehicleId=%s score=%s, "
            "near-tied candidates=%r",
            best.get("vehicleId"), best_score, rejected,
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
    """Kjøpslenker. Google Shopping treffer den eksakte delen + priser på tvers
    av norske butikker (stabilt format). Autodoc er affiliate-partner.
    Erstattes med ekte produktlenker per butikk når affiliate-feeds er på plass.
    """
    term = quote_plus(f"{brand} {article_no}".strip())
    art = quote_plus(article_no.strip())
    return [
        {"shop": "Sammenlign priser", "url": f"https://www.google.com/search?tbm=shop&q={term}"},
        {"shop": "Autodoc", "url": f"https://www.autodoc.co.no/search?keyword={art}"},
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


# ---------------------------------------------------------------------------
# Tekniske spesifikasjoner -- lastes kun når brukeren åpner en artikkel i
# detalj (aldri i lister). Feltnavnene katalogen returnerer varierer helt
# fritt per artikkeltype (en oljefilterartikkel og en bremseklosseartikkel
# har ingen felles skjema) -- vi normaliserer derfor til en stabil
# {label, value}-kontrakt i stedet for å eksponere katalogens rå feltnavn
# direkte til Flutter, og filtrerer bort ugyldige/tomme oppføringer her slik
# at appen aldri trenger å håndtere rå API-uregelmessigheter selv.
# ---------------------------------------------------------------------------
def _normalize_specifications(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("criteriaName") or item.get("label") or item.get("name")
        value = item.get("criteriaValue")
        if value is None:
            value = item.get("value")
        if not label or value in (None, ""):
            continue
        out.append({"label": str(label).strip(), "value": str(value).strip()})
    return out


async def specifications_for_article(article_id: int) -> list[dict]:
    """Normaliserte tekniske spesifikasjoner for én artikkel."""
    raw = await client.specifications(article_id)
    return _normalize_specifications(raw)
