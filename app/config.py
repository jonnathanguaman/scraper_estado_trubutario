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
    sri_headless: bool = Field(default=True, alias="SRI_HEADLESS")
    sri_browser_backend: str = Field(default="camoufox", alias="SRI_BROWSER_BACKEND")
    sri_timeout_ms: int = Field(default=60_000, alias="SRI_TIMEOUT_MS")
    sri_profile_dir: Path = Field(default=Path("storage/browser-profile"), alias="SRI_PROFILE_DIR")
    sri_chrome_path: Path | None = Field(default=None, alias="SRI_CHROME_PATH")
    sri_chrome_profile_dir: Path = Field(default=Path("storage/chrome-cdp-profile"), alias="SRI_CHROME_PROFILE_DIR")
    sri_cdp_port: int = Field(default=9222, alias="SRI_CDP_PORT")
    sri_rate_limit_seconds: float = Field(default=5.0, alias="SRI_RATE_LIMIT_SECONDS")
    sri_screenshot_dir: Path = Field(default=Path("storage/screenshots"), alias="SRI_SCREENSHOT_DIR")
    sri_capturas_dir: Path = Field(default=Path("storage/capturas"), alias="SRI_CAPTURAS_DIR")
    capsolver_api_key: str | None = Field(default=None, alias="CAPSOLVER_API_KEY")
    capsolver_log_token: bool = Field(default=False, alias="CAPSOLVER_LOG_TOKEN")
    capsolver_anchor: str | None = Field(default=None, alias="CAPSOLVER_ANCHOR")
    capsolver_reload: str | None = Field(default=None, alias="CAPSOLVER_RELOAD")
    twocaptcha_api_key: str | None = Field(default=None, alias="TWOCAPTCHA_API_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    app_name: str = "Extractor Estado Tributario SRI"


@lru_cache
def get_settings() -> Settings:
    return Settings()

