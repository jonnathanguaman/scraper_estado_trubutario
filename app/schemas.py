from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TipoIdentificacion(StrEnum):
    ruc_cedula = "ruc_cedula"
    pasaporte = "pasaporte"


class ConsultaRequest(BaseModel):
    identificacion: str = Field(min_length=1, max_length=20)
    tipo: TipoIdentificacion = TipoIdentificacion.ruc_cedula
    return_html: bool = True
    return_data: bool = True
    screenshot: bool = False

    @field_validator("identificacion")
    @classmethod
    def validar_identificacion(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("La identificación es obligatoria.")
        return cleaned

    @model_validator(mode="after")
    def validar_formato_basico(self) -> "ConsultaRequest":
        if self.tipo == TipoIdentificacion.ruc_cedula and not self.identificacion.isdigit():
            raise ValueError("RUC/cédula solo acepta números.")
        if self.tipo == TipoIdentificacion.ruc_cedula and len(self.identificacion) not in (10, 13):
            raise ValueError("RUC/cédula debe tener 10 o 13 dígitos.")
        return self


class EstadoTributarioData(BaseModel):
    identificacion: str | None = None
    nombre_razon_social: str | None = None
    estado_tributario: str | None = None
    permiso_facturacion: str | None = None
    obligaciones_presentacion: list[dict[str, Any]] = Field(default_factory=list)
    obligaciones_pago: list[dict[str, Any]] = Field(default_factory=list)
    deudas_firmes: Any | None = None
    mensajes: list[str] = Field(default_factory=list)
    raw_api: dict[str, Any] = Field(default_factory=dict)


class ConsultaResponse(BaseModel):
    status: Literal["ok", "not_found", "captcha_required", "timeout", "error"]
    identificacion: str
    message: str | None = None
    html: str | None = None
    data: EstadoTributarioData | None = None
    screenshot_path: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    playwright_available: bool
    browser_started: bool


class BrowserSessionResponse(BaseModel):
    status: Literal["started", "already_started", "closed"]
    profile_dir: str
