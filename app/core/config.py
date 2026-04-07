from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_v1_prefix: str = "/api/v1"
    project_name: str = "Mekko Backend"

    # Vegvesenet
    vegvesenet_api_key: str
    vegvesenet_base_url: str = (
        "https://akfell-datautlevering.atlas.vegvesen.no/enkeltoppslag/kjoretoydata"
    )

    # CORS — under utvikling tillater vi alt
    cors_origins: list[str] = ["*"]


settings = Settings()
