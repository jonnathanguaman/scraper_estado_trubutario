from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.schemas import EstadoTributarioData


SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def _pair_after_label(soup: BeautifulSoup, label: str) -> str | None:
    label_node = soup.find(string=lambda text: bool(text) and clean_text(text).lower() == label.lower())
    if not label_node:
        return None

    parent = label_node.parent
    if not parent:
        return None

    container = parent.find_parent(["div", "section", "article"]) or parent
    texts = [clean_text(item) for item in container.stripped_strings]
    texts = [item for item in texts if item]
    for index, item in enumerate(texts):
        if item.lower() == label.lower() and index + 1 < len(texts):
            return texts[index + 1]
    return None


def _extract_messages(soup: BeautifulSoup) -> list[str]:
    candidates = soup.select(".ui-messages-detail, .ui-message-detail, p-messages, .texto-mensaje-sin-informacion")
    messages: list[str] = []
    for node in candidates:
        text = clean_text(node.get_text(" "))
        if text and text not in messages:
            messages.append(text)
    return messages


def _rows_from_table(table: Any) -> list[dict[str, str]]:
    headers = [clean_text(header.get_text(" ")) for header in table.select("thead th")]
    rows: list[dict[str, str]] = []
    for tr in table.select("tbody tr"):
        cells = [clean_text(cell.get_text(" ")) for cell in tr.select("td")]
        if not any(cells):
            continue
        if headers and len(headers) == len(cells):
            rows.append(dict(zip(headers, cells, strict=False)))
        else:
            rows.append({f"columna_{index + 1}": value for index, value in enumerate(cells)})
    return rows


def parse_html(html: str, raw_api: dict[str, Any] | None = None) -> EstadoTributarioData:
    soup = BeautifulSoup(html, "lxml")
    data = EstadoTributarioData(raw_api=raw_api or {})

    data.identificacion = _pair_after_label(soup, "Identificación")
    data.nombre_razon_social = _pair_after_label(soup, "Nombre/Razón social")

    page_text = clean_text(soup.get_text(" "))
    status_match = re.search(
        r"(AL D[IÍ]A EN SUS OBLIGACIONES|NO SE ENCUENTRA AL D[IÍ]A|SIN OBLIGACIONES)",
        page_text,
        re.IGNORECASE,
    )
    if status_match:
        data.estado_tributario = clean_text(status_match.group(1)).upper()

    permiso_match = re.search(r"(?:vigencia|permiso).*?(0|3|12)\s*mes", page_text, re.IGNORECASE)
    if permiso_match:
        data.permiso_facturacion = permiso_match.group(0)

    tables = soup.select("table")
    if tables:
        data.obligaciones_presentacion = _rows_from_table(tables[0])
    if len(tables) > 1:
        data.obligaciones_pago = _rows_from_table(tables[1])

    data.mensajes = _extract_messages(soup)
    _merge_raw_api(data, raw_api or {})
    return data


def _merge_raw_api(data: EstadoTributarioData, raw_api: dict[str, Any]) -> None:
    persona = raw_api.get("persona")
    if isinstance(persona, dict):
        data.identificacion = data.identificacion or persona.get("identificacion") or persona.get("numeroIdentificacion")
        data.nombre_razon_social = (
            data.nombre_razon_social
            or persona.get("nombreCompleto")
            or persona.get("razonSocial")
            or persona.get("nombre")
        )

    estado = raw_api.get("estado_tributario")
    if isinstance(estado, dict):
        data.estado_tributario = data.estado_tributario or estado.get("textoEstadoTributario")
        data.obligaciones_presentacion = estado.get("dtObligacionesPendientesPresentacion") or data.obligaciones_presentacion
        data.obligaciones_pago = estado.get("dtObligacionesPendientesPago") or data.obligaciones_pago
        data.deudas_firmes = estado.get("deudasFirmes", data.deudas_firmes)

    permiso = raw_api.get("permiso_facturacion")
    if isinstance(permiso, dict):
        permiso_value = permiso.get("permisoFacturacion") or permiso.get("textoPermisoFacturacion")
        data.permiso_facturacion = data.permiso_facturacion or permiso_value

