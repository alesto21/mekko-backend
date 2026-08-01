from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_v1_prefix: str = "/api/v1"
    project_name: str = "MinBil Backend"

    # Vegvesenet
    vegvesenet_api_key: str = ""
    vegvesenet_base_url: str = (
        "https://akfell-datautlevering.atlas.vegvesen.no/enkeltoppslag/kjoretoydata"
    )

    # Anthropic (AI-mekaniker)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_max_tokens: int = 1024

    # Feedback (Discord webhook for in-app tilbakemelding)
    discord_webhook_url: str = ""

    # RevenueCat — server-side entitlement-verifikasjon.
    # Secret v1 API-nøkkel (IKKE samme som SDK-nøkkelen i Flutter-appen).
    # Tom streng = kill switch: verifisering skrus av, chat.py/scan.py
    # faller tilbake til å stole på klientens is_pro-felt som i dag. Dette
    # er en nød-/kompatibilitetsmekanisme, ikke tilsiktet langtidsdrift —
    # se app/services/revenuecat.py.
    revenuecat_secret_key: str = ""
    revenuecat_entitlement_id: str = "pro_access"
    revenuecat_verification_cache_ttl_seconds: int = 60

    # TecDoc-katalog (reservedeler/fitment via RapidAPI "auto-parts-catalog")
    rapidapi_key: str = ""
    rapidapi_host: str = "auto-parts-catalog.p.rapidapi.com"
    tecdoc_lang_id: int = 12       # 12 = Norsk
    tecdoc_country_id: int = 167   # 167 = Norge
    tecdoc_type_id: int = 1        # 1 = personbiler

    # CORS — under utvikling tillater vi alt
    cors_origins: list[str] = ["*"]


settings = Settings()
