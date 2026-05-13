from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.schemas import EstadoTributarioData


SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def parse_html(html: str, raw_api: dict[str, Any] | None = None) -> EstadoTributarioData:
    soup = BeautifulSoup(html, "lxml")
    data = EstadoTributarioData()

    page_text = clean_text(soup.get_text(" "))

    resultado = _extract_estado_resultado(page_text)
    if resultado:
        data.estado_tributario.resultado = resultado

    vigencia = _extract_vigencia(page_text)
    if vigencia:
        data.permiso_facturacion.vigencia = vigencia

    _merge_raw_api(data, raw_api or {})
    return data


def _extract_estado_resultado(text: str) -> str | None:
    match = re.search(
        r"(AL D[IÍ]A EN SUS OBLIGACIONES|NO SE ENCUENTRA AL D[IÍ]A|SIN OBLIGACIONES)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return clean_text(match.group(1)).upper()


def _extract_vigencia(text: str) -> str | None:
    match = re.search(r"(0|3|12)\s*mes(?:es)?", text, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1)} meses"


def _merge_raw_api(data: EstadoTributarioData, raw_api: dict[str, Any]) -> None:
    estado = raw_api.get("estado_tributario")
    if isinstance(estado, dict):
        data.estado_tributario.resultado = (
            data.estado_tributario.resultado
            or _normalizar_resultado(estado.get("textoEstadoTributario"))
        )

    permiso = raw_api.get("permiso_facturacion")
    if isinstance(permiso, dict):
        permiso_value = permiso.get("permisoFacturacion") or permiso.get("textoPermisoFacturacion")
        data.permiso_facturacion.vigencia = (
            data.permiso_facturacion.vigencia
            or _normalizar_vigencia(permiso_value)
        )


def _normalizar_resultado(value: Any) -> str | None:
    text = clean_text(str(value)) if value is not None else ""
    return text.upper() or None


def _normalizar_vigencia(value: Any) -> str | None:
    text = clean_text(str(value)) if value is not None else ""
    upper = text.upper()
    if upper == "TOTAL":
        return "12 meses"
    if upper == "PARCIAL":
        return "3 meses"
    if upper in {"NINGUNO", "NO", "0"}:
        return "0 meses"
    return _extract_vigencia(text) or text or None
