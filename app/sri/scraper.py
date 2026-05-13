from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.schemas import ConsultaRequest, ConsultaResponse, EstadoTributarioData, TipoIdentificacion
from app.sri.browser import SriBrowserManager
from app.sri.parser import parse_html


class SriScraper:
    def __init__(self, browser: SriBrowserManager, settings: Settings) -> None:
        self.browser = browser
        self.settings = settings
        self._last_request_at = 0.0

    async def consultar(self, request: ConsultaRequest) -> ConsultaResponse:
        async with self.browser.lock:
            await self._rate_limit()
            page = await self.browser.page()
            network_payloads: dict[str, Any] = {}
            self._attach_response_listener(page, network_payloads)

            try:
                await self._open_form(page)
                await self._fill_form(page, request)
                await self._submit(page)
                status = await self._wait_for_outcome(page)
                html = await page.content()
                screenshot_path = await self._screenshot(page, request.identificacion) if request.screenshot else None

                if status == "captcha_required":
                    return ConsultaResponse(
                        status="captcha_required",
                        identificacion=request.identificacion,
                        message="Se requiere resolver reCAPTCHA manualmente en la sesión del navegador.",
                        html=html if request.return_html else None,
                        data=parse_html(html, network_payloads) if request.return_data else None,
                        screenshot_path=screenshot_path,
                    )

                data = parse_html(html, network_payloads) if request.return_data else None
                response_status = self._classify_response(data, html)
                return ConsultaResponse(
                    status=response_status,
                    identificacion=request.identificacion,
                    html=None,
                    data=data,
                    screenshot_path=screenshot_path,
                )
            except PlaywrightTimeoutError:
                html = await self._safe_content(page)
                return ConsultaResponse(
                    status="timeout",
                    identificacion=request.identificacion,
                    message="Se agotó el tiempo esperando la respuesta del SRI.",
                    html=html if request.return_html else None,
                    data=parse_html(html, network_payloads) if html and request.return_data else None,
                )
            except PlaywrightError as exc:
                html = await self._safe_content(page)
                return ConsultaResponse(
                    status="error",
                    identificacion=request.identificacion,
                    message=str(exc),
                    html=html if request.return_html else None,
                    data=parse_html(html, network_payloads) if html and request.return_data else None,
                )

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.settings.sri_rate_limit_seconds - elapsed
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        self._last_request_at = time.monotonic()

    async def _open_form(self, page: Page) -> None:
        await page.goto(str(self.settings.sri_url), wait_until="domcontentloaded")
        await page.wait_for_selector("sri-consulta-estado-tributario-web-app", state="attached")
        await page.wait_for_selector("#busquedaRucId, input[placeholder*='Pasaporte']", state="attached")

    async def _fill_form(self, page: Page, request: ConsultaRequest) -> None:
        if request.tipo == TipoIdentificacion.pasaporte:
            await page.get_by_role("button", name="Pasaporte").click()
            field = page.locator("input").filter(has_not_text="").last
        else:
            field = page.locator("#busquedaRucId")

        await field.fill(request.identificacion)
        await page.wait_for_timeout(300)

    async def _submit(self, page: Page) -> None:
        button = page.get_by_role("button", name="Consultar")
        await button.wait_for(state="visible")
        await button.click()

    async def _wait_for_outcome(self, page: Page) -> str:
        checks = [
            asyncio.create_task(
                page.wait_for_selector(
                    "text=/Identificación|Nombre\\/Razón social|Información general/i",
                    timeout=self.settings.sri_timeout_ms,
                )
            ),
            asyncio.create_task(
                page.wait_for_selector(
                    "text=/no se encuentra en la base de datos|no tiene obligaciones|No se encontraron registros|No se pudo generar el token de reCAPTCHA|No se pudo generar el token/i",
                    timeout=self.settings.sri_timeout_ms,
                )
            ),
        ]
        done, pending = await asyncio.wait(checks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        first = done.pop()
        try:
            await first
        except PlaywrightTimeoutError:
            if await self._has_visible_recaptcha_challenge(page):
                return "captcha_required"
        return "ok"

    async def _has_visible_recaptcha_challenge(self, page: Page) -> bool:
        frames = page.locator("iframe[src*='recaptcha'][src*='bframe'], iframe[title*='desafío'], iframe[title*='challenge']")
        try:
            count = await frames.count()
            for index in range(count):
                if await frames.nth(index).is_visible():
                    return True
        except PlaywrightError:
            return False
        return False

    def _attach_response_listener(self, page: Page, payloads: dict[str, Any]) -> None:
        async def on_response(response: Any) -> None:
            url = response.url
            key = self._payload_key(url)
            if not key:
                return
            try:
                payloads[key] = await response.json()
            except Exception:
                payloads[key] = {"status": response.status, "url": url}

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

    def _payload_key(self, url: str) -> str | None:
        if "/Persona/obtenerPorTipoIdentificacion" in url:
            return "persona"
        if "/DatosRegistroCivil/" in url:
            return "registro_civil"
        if "/estado-tributario/consulta/persona/" in url:
            return "estado_tributario"
        if "/permiso-facturacion/consulta/persona/" in url:
            return "permiso_facturacion"
        return None

    async def _screenshot(self, page: Page, identificacion: str) -> str:
        self.settings.sri_screenshot_dir.mkdir(parents=True, exist_ok=True)
        suffix = identificacion[-4:].rjust(4, "x")
        filename = f"consulta-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}.png"
        path = self.settings.sri_screenshot_dir / filename
        await page.screenshot(path=str(path), full_page=True)
        return str(Path(path))

    async def _safe_content(self, page: Page) -> str | None:
        try:
            return await page.content()
        except PlaywrightError:
            return None

    def _classify_response(self, data: EstadoTributarioData | None, html: str) -> str:
        text = html.lower()
        if "no se encuentra en la base de datos" in text:
            return "not_found"
        if data and (data.estado_tributario.resultado or data.permiso_facturacion.vigencia):
            return "ok"
        return "ok"
