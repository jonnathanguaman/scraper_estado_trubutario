from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.logging_config import mask_identification
from app.schemas import ConsultaRequest, ConsultaResponse, EstadoTributarioData, TipoIdentificacion
from app.sri.browser import SriBrowserManager
from app.sri.parser import parse_html

logger = logging.getLogger(__name__)


class SriScraper:
    def __init__(self, browser: SriBrowserManager, settings: Settings) -> None:
        self.browser = browser
        self.settings = settings
        self._last_request_at = 0.0

    async def consultar(self, request: ConsultaRequest) -> ConsultaResponse:
        started_at = time.monotonic()
        masked_id = mask_identification(request.identificacion)
        logger.info(
            "consulta_start identificacion=%s tipo=%s return_html=%s return_data=%s screenshot=%s",
            masked_id,
            request.tipo,
            request.return_html,
            request.return_data,
            request.screenshot,
        )

        async with self.browser.lock:
            logger.debug("consulta_lock_acquired identificacion=%s", masked_id)
            await self._rate_limit()
            page = await self.browser.page()
            self._attach_page_diagnostics(page)
            network_payloads: dict[str, Any] = {}
            self._attach_response_listener(page, network_payloads)

            try:
                logger.info("consulta_step=open_form identificacion=%s", masked_id)
                await self._open_form(page)
                logger.info("consulta_step=fill_form identificacion=%s", masked_id)
                await self._fill_form(page, request)
                logger.info("consulta_step=submit identificacion=%s", masked_id)
                await self._submit(page)
                logger.info("consulta_step=wait_outcome identificacion=%s", masked_id)
                status = await self._wait_for_outcome(page, network_payloads)
                logger.info(
                    "consulta_outcome identificacion=%s outcome=%s payloads=%s elapsed_ms=%s",
                    masked_id,
                    status,
                    sorted(network_payloads.keys()),
                    self._elapsed_ms(started_at),
                )

                html = await page.content()
                logger.debug("consulta_html_captured identificacion=%s bytes=%s", masked_id, len(html.encode("utf-8")))
                screenshot_path = await self._screenshot(page, request.identificacion) if request.screenshot else None

                if status == "captcha_required":
                    logger.warning("consulta_captcha_required identificacion=%s", masked_id)
                    return ConsultaResponse(
                        status="captcha_required",
                        identificacion=request.identificacion,
                        message="Se requiere resolver reCAPTCHA manualmente en la sesion del navegador.",
                        html=html if request.return_html else None,
                        data=parse_html(html, network_payloads) if request.return_data else None,
                        screenshot_path=screenshot_path,
                    )

                data = parse_html(html, network_payloads) if request.return_data else None
                response_status = self._classify_response(data, html)
                logger.info(
                    "consulta_finished identificacion=%s status=%s data_estado=%s data_vigencia=%s elapsed_ms=%s",
                    masked_id,
                    response_status,
                    data.estado_tributario.resultado if data else None,
                    data.permiso_facturacion.vigencia if data else None,
                    self._elapsed_ms(started_at),
                )
                return ConsultaResponse(
                    status=response_status,
                    identificacion=request.identificacion,
                    html=None,
                    data=data,
                    screenshot_path=screenshot_path,
                )
            except PlaywrightTimeoutError:
                diagnostics = await self._collect_timeout_diagnostics(page, network_payloads)
                logger.error(
                    "consulta_timeout identificacion=%s elapsed_ms=%s diagnostics=%s",
                    masked_id,
                    self._elapsed_ms(started_at),
                    diagnostics,
                )
                html = await self._safe_content(page)
                return ConsultaResponse(
                    status="timeout",
                    identificacion=request.identificacion,
                    message="Se agoto el tiempo esperando la respuesta del SRI. Revise logs para diagnostico.",
                    html=html if request.return_html else None,
                    data=parse_html(html, network_payloads) if html and request.return_data else None,
                )
            except PlaywrightError as exc:
                logger.exception(
                    "consulta_playwright_error identificacion=%s elapsed_ms=%s error=%s",
                    masked_id,
                    self._elapsed_ms(started_at),
                    exc,
                )
                html = await self._safe_content(page)
                return ConsultaResponse(
                    status="error",
                    identificacion=request.identificacion,
                    message=str(exc),
                    html=html if request.return_html else None,
                    data=parse_html(html, network_payloads) if html and request.return_data else None,
                )
            finally:
                await self._safe_close_page(page)

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.settings.sri_rate_limit_seconds - elapsed
        if wait_for > 0:
            logger.info("rate_limit_sleep seconds=%.2f", wait_for)
            await asyncio.sleep(wait_for)
        self._last_request_at = time.monotonic()

    async def _open_form(self, page: Page) -> None:
        logger.debug("page_goto_start url=%s", self.settings.sri_url)
        response = await self._goto_sri(page)
        logger.info("page_goto_done status=%s url=%s", response.status if response else None, page.url)
        await self._wait_for_form_ready(page)
        logger.info("page_form_ready title=%s url=%s", await page.title(), page.url)

    async def _goto_sri(self, page: Page) -> Any:
        url = str(self.settings.sri_url)
        timeout = min(self.settings.sri_timeout_ms, 25_000)
        try:
            return await page.goto(url, wait_until="commit", timeout=timeout)
        except PlaywrightTimeoutError:
            logger.warning(
                "page_goto_commit_timeout url=%s current_url=%s snapshot=%s",
                url,
                page.url,
                await self._safe_text_snapshot(page),
            )

        try:
            logger.info("page_goto_fallback_assign_location url=%s", url)
            await page.evaluate("(target) => { window.location.href = target; }", url)
            await page.wait_for_url("**/consultaEstadoTributario", timeout=timeout)
        except PlaywrightTimeoutError:
            logger.warning(
                "page_goto_fallback_timeout current_url=%s html_prefix=%s",
                page.url,
                (await self._safe_content(page) or "")[:300],
            )
            raise
        return None

    async def _wait_for_form_ready(self, page: Page) -> None:
        selectors = [
            "sri-consulta-estado-tributario-web-app",
            "#busquedaRucId",
            "text=/Consultar informacion del contribuyente|Consultar información del contribuyente/i",
        ]
        deadline = time.monotonic() + (self.settings.sri_timeout_ms / 1000)
        last_snapshot = ""
        while time.monotonic() < deadline:
            for selector in selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        logger.debug("page_form_selector_found selector=%s", selector)
                        if await page.locator("#busquedaRucId").count() > 0:
                            return
                except PlaywrightError:
                    continue
            snapshot = await self._safe_text_snapshot(page)
            if snapshot and snapshot != last_snapshot:
                logger.debug("page_wait_form_snapshot url=%s text=%s", page.url, snapshot[:500])
                last_snapshot = snapshot
            await asyncio.sleep(0.5)
        raise PlaywrightTimeoutError("No se encontro el formulario de Estado Tributario en la pagina SRI")

    async def _fill_form(self, page: Page, request: ConsultaRequest) -> None:
        if request.tipo == TipoIdentificacion.pasaporte:
            logger.debug("form_select_pasaporte")
            await page.get_by_role("button", name="Pasaporte").click()
            field = page.locator("input").last
        else:
            field = page.locator("#busquedaRucId")

        await field.fill(request.identificacion)
        await page.wait_for_timeout(300)
        filled_value = await field.input_value()
        logger.info(
            "form_identificacion_filled identificacion=%s value_length=%s",
            mask_identification(request.identificacion),
            len(filled_value),
        )

    async def _submit(self, page: Page) -> None:
        button = page.get_by_role("button", name="Consultar")
        await button.wait_for(state="visible")
        await self._wait_until_button_enabled(page, button)
        logger.info("form_submit_button_enabled")
        await button.click()
        logger.info("form_submitted")

    async def _wait_for_outcome(self, page: Page, payloads: dict[str, Any]) -> str:
        checks = [
            asyncio.create_task(
                page.wait_for_selector(
                    "text=/AL D.A EN SUS OBLIGACIONES|SIN OBLIGACIONES|NO SE ENCUENTRA|Resultado|Permiso de facturaci/i",
                    timeout=self.settings.sri_timeout_ms,
                )
            ),
            asyncio.create_task(
                page.wait_for_selector(
                    "text=/no se encuentra en la base de datos|no tiene obligaciones|No se encontraron registros|No se pudo generar el token de reCAPTCHA|No se pudo generar el token/i",
                    timeout=self.settings.sri_timeout_ms,
                )
            ),
            asyncio.create_task(self._wait_for_network_payloads(payloads)),
        ]
        done, pending = await asyncio.wait(checks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        for task in done:
            try:
                result = await task
                if result == "network_payloads_ready":
                    return "ok"
            except PlaywrightTimeoutError:
                continue

        if await self._has_visible_recaptcha_challenge(page):
            logger.warning("visible_recaptcha_challenge_detected")
            return "captcha_required"
        return "ok"

    async def _wait_for_network_payloads(self, payloads: dict[str, Any]) -> str:
        deadline = time.monotonic() + (self.settings.sri_timeout_ms / 1000)
        while time.monotonic() < deadline:
            if "estado_tributario" in payloads and "permiso_facturacion" in payloads:
                logger.info("network_payloads_ready keys=%s", sorted(payloads.keys()))
                return "network_payloads_ready"
            await asyncio.sleep(0.25)
        raise PlaywrightTimeoutError("Timeout esperando payloads internos del SRI")

    async def _has_visible_recaptcha_challenge(self, page: Page) -> bool:
        frames = page.locator("iframe[src*='recaptcha'][src*='bframe'], iframe[title*='challenge']")
        try:
            count = await frames.count()
            logger.debug("recaptcha_challenge_frames count=%s", count)
            for index in range(count):
                if await frames.nth(index).is_visible():
                    return True
        except PlaywrightError:
            return False
        return False

    async def _wait_until_button_enabled(self, page: Page, button: Any) -> None:
        deadline = time.monotonic() + min(self.settings.sri_timeout_ms / 1000, 15)
        last_state: tuple[bool | None, str | None] | None = None
        while time.monotonic() < deadline:
            try:
                is_enabled = await button.is_enabled()
                disabled_attr = await button.get_attribute("disabled")
                state = (is_enabled, disabled_attr)
                if state != last_state:
                    logger.debug("submit_button_state enabled=%s disabled_attr=%s", is_enabled, disabled_attr)
                    last_state = state
                if is_enabled and disabled_attr is None:
                    return
            except PlaywrightError:
                pass
            await asyncio.sleep(0.25)
        logger.error("submit_button_still_disabled snapshot=%s", await self._safe_text_snapshot(page))
        raise PlaywrightTimeoutError("El boton Consultar no se habilito despues de llenar la identificacion")

    def _attach_response_listener(self, page: Page, payloads: dict[str, Any]) -> None:
        async def on_response(response: Any) -> None:
            url = response.url
            if response.status >= 400:
                logger.warning("network_response_error status=%s url=%s", response.status, url)
            key = self._payload_key(url)
            if not key:
                return
            try:
                payloads[key] = await response.json()
                logger.info("network_payload_captured key=%s status=%s", key, response.status)
            except Exception:
                payloads[key] = {"status": response.status, "url": url}
                logger.warning("network_payload_non_json key=%s status=%s url=%s", key, response.status, url)

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

    def _attach_page_diagnostics(self, page: Page) -> None:
        if getattr(page, "_sri_diagnostics_attached", False):
            return
        setattr(page, "_sri_diagnostics_attached", True)
        page.on("console", lambda msg: logger.debug("browser_console type=%s text=%s", msg.type, msg.text[:500]))
        page.on("pageerror", lambda exc: logger.warning("browser_page_error error=%s", exc))
        page.on(
            "requestfailed",
            lambda request: logger.warning(
                "network_request_failed method=%s url=%s failure=%s",
                request.method,
                request.url,
                request.failure,
            ),
        )

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
        logger.info("screenshot_saved path=%s", path)
        return str(Path(path))

    async def _safe_content(self, page: Page) -> str | None:
        try:
            return await page.content()
        except PlaywrightError:
            return None

    async def _safe_close_page(self, page: Page) -> None:
        try:
            if not page.is_closed():
                await page.close()
                logger.debug("browser_page_closed")
        except PlaywrightError:
            logger.debug("browser_page_close_failed", exc_info=True)

    async def _safe_text_snapshot(self, page: Page) -> str:
        try:
            text = await page.locator("body").inner_text(timeout=2000)
            return " ".join(text.split())[:1000]
        except PlaywrightError:
            return ""

    async def _collect_timeout_diagnostics(self, page: Page, payloads: dict[str, Any]) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "url": page.url,
            "payload_keys": sorted(payloads.keys()),
            "visible_recaptcha": await self._has_visible_recaptcha_challenge(page),
            "body_text": await self._safe_text_snapshot(page),
        }
        try:
            diagnostics["button_enabled"] = await page.get_by_role("button", name="Consultar").is_enabled(timeout=1000)
        except PlaywrightError:
            diagnostics["button_enabled"] = None
        try:
            diagnostics["input_value_length"] = len(await page.locator("#busquedaRucId").input_value(timeout=1000))
        except PlaywrightError:
            diagnostics["input_value_length"] = None
        return diagnostics

    def _classify_response(self, data: EstadoTributarioData | None, html: str) -> str:
        text = html.lower()
        if "no se encuentra en la base de datos" in text:
            return "not_found"
        if data and (data.estado_tributario.resultado or data.permiso_facturacion.vigencia):
            return "ok"
        return "ok"

    def _elapsed_ms(self, started_at: float) -> int:
        return round((time.monotonic() - started_at) * 1000)
