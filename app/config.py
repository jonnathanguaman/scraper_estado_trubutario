from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sri_url: AnyHttpUrl = Field(
        default="https://srienlinea.sri.gob.ec/sri-en-linea/SriDeclaracionesWeb/EstadoTributario/Consultas/consultaEstadoTributario",
        alias="SRI_URL",
    )
    sri_headless: bool = Field(default=False, alias="SRI_HEADLESS")
    sri_timeout_ms: int = Field(default=60_000, alias="SRI_TIMEOUT_MS")
    sri_profile_dir: Path = Field(default=Path("storage/browser-profile"), alias="SRI_PROFILE_DIR")
    sri_rate_limit_seconds: float = Field(default=5.0, alias="SRI_RATE_LIMIT_SECONDS")
    sri_screenshot_dir: Path = Field(default=Path("storage/screenshots"), alias="SRI_SCREENSHOT_DIR")

    app_name: str = "Extractor Estado Tributario SRI"


@lru_cache
def get_settings() -> Settings:
    return Settings()

