from __future__ import annotations

import asyncio
import json
import logging
import random
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

_FIELD_RUC_ID = "#busquedaRucId"
_HUMAN_TYPE_MIN_SECONDS = 5.0
_HUMAN_TYPE_PAUSE_MIN = 0.08
_HUMAN_TYPE_PAUSE_MAX = 0.35
_HUMAN_MOUSE_STEPS_MIN = 8
_HUMAN_MOUSE_STEPS_MAX = 18


class SriScraper:
    def __init__(self, browser: SriBrowserManager, settings: Settings) -> None:
        self.browser = browser
        self.settings = settings
        self._last_request_at = 0.0

    async def consultar(self, request: ConsultaRequest) -> ConsultaResponse:
        result = await self._consultar_once(request)
        if result.status == "captcha_required":
            logger.warning("captcha_umbral_bajo_reseteando_perfil")
            await self._reset_profile()
            logger.info("captcha_perfil_reseteado_reintentando")
            result = await self._consultar_once(request)
        return result

    async def _reset_profile(self) -> None:
        import shutil
        profile_dir = self.browser.profile_dir()
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
            logger.info("browser_profile_deleted path=%s", profile_dir)

    async def _consultar_once(self, request: ConsultaRequest) -> ConsultaResponse:
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
                if self.settings.twocaptcha_api_key or self.settings.capsolver_api_key:
                    await self._inject_capsolver_token(page)
                logger.info("consulta_step=submit identificacion=%s", masked_id)
                await self._submit(page)
                logger.info("consulta_step=wait_outcome identificacion=%s", masked_id)
                status = await self._wait_for_outcome(page, network_payloads)
                if "permiso_facturacion" not in network_payloads:
                    await self._wait_for_permiso_facturacion(page, network_payloads)
                if "captcha_validation_error" in network_payloads:
                    status = "captcha_required"

                logger.info(
                    "consulta_outcome identificacion=%s outcome=%s payloads=%s elapsed_ms=%s",
                    masked_id,
                    status,
                    sorted(network_payloads.keys()),
                    self._elapsed_ms(started_at),
                )

                return await self._build_response(
                    page, request, network_payloads, status, masked_id, started_at
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
                    message="Se agoto el tiempo esperando la respuesta del SRI.",
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
                await self.browser.stop()

    async def _build_response(
        self,
        page: Page,
        request: ConsultaRequest,
        network_payloads: dict[str, Any],
        status: str,
        masked_id: str,
        started_at: float,
    ) -> ConsultaResponse:
        html = await page.content()
        screenshot_path = await self._screenshot(page, request.identificacion) if request.screenshot else None

        if status == "captcha_required":
            logger.warning("consulta_captcha_required identificacion=%s", masked_id)
            return ConsultaResponse(
                status="captcha_required",
                identificacion=request.identificacion,
                message=self._captcha_error_message(network_payloads)
                or "Se requiere resolver reCAPTCHA manualmente en la sesion del navegador.",
                html=html if request.return_html else None,
                data=None,
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
            html=html if request.return_html else None,
            data=data,
            screenshot_path=screenshot_path,
        )

    # ------------------------------------------------------------------ #
    # Navegación y formulario                                              #
    # ------------------------------------------------------------------ #

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.settings.sri_rate_limit_seconds - elapsed
        if wait_for > 0:
            logger.info("rate_limit_sleep seconds=%.2f", wait_for)
            await asyncio.sleep(wait_for)
        self._last_request_at = time.monotonic()

    async def _open_form(self, page: Page) -> None:
        response = await self._goto_sri(page)
        logger.info("page_goto_done status=%s url=%s", response.status if response else None, page.url)
        await self._wait_for_form_ready(page)
        logger.info("browser_validation_state state=%s", await self._browser_validation_state(page))
        logger.info("page_form_ready title=%s url=%s", await page.title(), page.url)

    async def _goto_sri(self, page: Page) -> Any:
        url = str(self.settings.sri_url)
        timeout = min(self.settings.sri_timeout_ms, 25_000)
        try:
            return await page.goto(url, wait_until="commit", timeout=timeout)
        except PlaywrightTimeoutError:
            logger.warning("page_goto_commit_timeout url=%s current_url=%s", url, page.url)

        try:
            await page.evaluate("(target) => { window.location.href = target; }", url)
            await page.wait_for_url("**/consultaEstadoTributario", timeout=timeout)
        except PlaywrightTimeoutError:
            logger.warning("page_goto_fallback_timeout current_url=%s", page.url)
            raise
        return None

    async def _wait_for_form_ready(self, page: Page) -> None:
        selectors = [
            "sri-consulta-estado-tributario-web-app",
            _FIELD_RUC_ID,
            "text=/Consultar informacion del contribuyente|Consultar información del contribuyente/i",
        ]
        deadline = time.monotonic() + (self.settings.sri_timeout_ms / 1000)
        while time.monotonic() < deadline:
            for selector in selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        if await page.locator(_FIELD_RUC_ID).count() > 0:
                            return
                except PlaywrightError:
                    continue
            await asyncio.sleep(0.5)
        raise PlaywrightTimeoutError("No se encontro el formulario de Estado Tributario en la pagina SRI")

    async def _fill_form(self, page: Page, request: ConsultaRequest) -> None:
        if request.tipo == TipoIdentificacion.pasaporte:
            await page.get_by_role("button", name="Pasaporte").click()
            field = page.locator("input").last
        else:
            field = page.locator(_FIELD_RUC_ID)

        await self._human_type(page, field, request.identificacion)
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
        await self._human_move_to_locator(page, button)
        await self._human_pause(0.35, 1.1)
        await button.click()
        logger.info("form_submitted")

    # ------------------------------------------------------------------ #
    # Capsolver — inyección de token reCAPTCHA Enterprise                 #
    # ------------------------------------------------------------------ #

    async def _inject_capsolver_token(self, page: Page) -> None:
        from urllib.parse import quote
        from urllib.parse import unquote

        from app.sri.captcha import solve_recaptcha_enterprise_with_metadata, solve_with_twocaptcha

        try:
            if self.settings.twocaptcha_api_key:
                solution = await solve_with_twocaptcha(self.settings.twocaptcha_api_key)
            else:
                solution = await solve_recaptcha_enterprise_with_metadata(  # type: ignore[arg-type]
                    self.settings.capsolver_api_key,
                    log_token=self.settings.capsolver_log_token,
                    anchor=self.settings.capsolver_anchor,
                    reload=self.settings.capsolver_reload,
                )
        except Exception:
            logger.exception("captcha_solve_failed — continuando sin token")
            return

        # Interceptar la petición HTTP al validador de captcha del SRI y
        # reemplazar el token de Google con el token resuelto por Capsolver.
        # Esto es más robusto que parchear grecaptcha.enterprise.execute en JS
        # porque Angular puede haber capturado la referencia de la función antes
        # de nuestra inyección.
        encoded_token = quote(solution.token, safe="")

        async def _route_captcha(route, request) -> None:  # type: ignore[no-untyped-def]
            url = request.url
            if "googleCaptchaResponse=" in url:
                import re
                original_match = re.search(r"googleCaptchaResponse=([^&]*)", url)
                if original_match and self.settings.capsolver_log_token:
                    logger.warning(
                        "sri_original_recaptcha_token token=%s",
                        unquote(original_match.group(1)),
                    )
                new_url = re.sub(r"googleCaptchaResponse=[^&]*", f"googleCaptchaResponse={encoded_token}", url)
                if "emitirToken=" not in new_url:
                    separator = "&" if "?" in new_url else "?"
                    new_url = f"{new_url}{separator}emitirToken=true"
                headers = dict(request.headers)
                if solution.user_agent:
                    headers["user-agent"] = solution.user_agent
                if solution.sec_ch_ua:
                    headers["sec-ch-ua"] = solution.sec_ch_ua
                logger.info("captcha_request_token_replaced url_len=%s", len(new_url))
                if self.settings.capsolver_log_token:
                    logger.warning("sri_replaced_recaptcha_token token=%s", solution.token)
                    logger.warning("sri_replaced_recaptcha_url url=%s", new_url)
                await route.continue_(url=new_url, headers=headers)
            else:
                await route.continue_()

        await page.route("**/validarGoogleReCaptcha**", _route_captcha)
        logger.info(
            "capsolver_route_installed token_length=%s apply_user_agent=%s apply_sec_ch_ua=%s",
            len(solution.token),
            bool(solution.user_agent),
            bool(solution.sec_ch_ua),
        )

    # ------------------------------------------------------------------ #
    # Espera de resultado                                                  #
    # ------------------------------------------------------------------ #

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
                    "text=/no se encuentra en la base de datos|no tiene obligaciones|No se encontraron registros|No se pudo generar el token/i",
                    timeout=self.settings.sri_timeout_ms,
                )
            ),
            asyncio.create_task(self._wait_for_network_payloads(payloads)),
            asyncio.create_task(self._wait_for_captcha_validation_error(payloads)),
        ]
        done, pending = await asyncio.wait(checks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        for task in done:
            try:
                result = await task
                if result == "network_payloads_ready":
                    return "ok"
                if result == "captcha_validation_error":
                    return "captcha_required"
            except PlaywrightTimeoutError:
                continue

        if "captcha_validation_error" in payloads:
            return "captcha_required"
        if await self._has_visible_recaptcha_challenge(page):
            logger.warning("visible_recaptcha_challenge_detected")
            return "captcha_required"
        return "ok"

    async def _wait_for_permiso_facturacion(self, page: Page, payloads: dict[str, Any]) -> None:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if "permiso_facturacion" in payloads:
                return
            try:
                found = await page.evaluate("() => /\\d+\\s*mes(?:es)?/i.test(document.body.innerText)")
                if found:
                    return
            except PlaywrightError:
                pass
            await asyncio.sleep(0.25)
        logger.warning("permiso_facturacion_wait_timeout")

    async def _wait_for_network_payloads(self, payloads: dict[str, Any]) -> str:
        deadline = time.monotonic() + (self.settings.sri_timeout_ms / 1000)
        while time.monotonic() < deadline:
            if "estado_tributario" in payloads and "permiso_facturacion" in payloads:
                logger.info("network_payloads_ready keys=%s", sorted(payloads.keys()))
                return "network_payloads_ready"
            if "captcha_validation_error" in payloads:
                return "captcha_validation_error"
            await asyncio.sleep(0.25)
        raise PlaywrightTimeoutError("Timeout esperando payloads internos del SRI")

    async def _wait_for_captcha_validation_error(self, payloads: dict[str, Any]) -> str:
        deadline = time.monotonic() + min(self.settings.sri_timeout_ms / 1000, 15)
        while time.monotonic() < deadline:
            if "captcha_validation_error" in payloads:
                return "captcha_validation_error"
            await asyncio.sleep(0.25)
        raise PlaywrightTimeoutError("Timeout esperando error de validacion captcha")

    async def _has_visible_recaptcha_challenge(self, page: Page) -> bool:
        frames = page.locator("iframe[src*='recaptcha'][src*='bframe'], iframe[title*='challenge']")
        try:
            for i in range(await frames.count()):
                if await frames.nth(i).is_visible():
                    return True
        except PlaywrightError:
            pass
        return False

    async def _wait_until_button_enabled(self, page: Page, button: Any) -> None:
        deadline = time.monotonic() + min(self.settings.sri_timeout_ms / 1000, 15)
        while time.monotonic() < deadline:
            try:
                if await button.is_enabled() and await button.get_attribute("disabled") is None:
                    return
            except PlaywrightError:
                pass
            await asyncio.sleep(0.25)
        logger.error("submit_button_still_disabled snapshot=%s", await self._safe_text_snapshot(page))
        raise PlaywrightTimeoutError("El boton Consultar no se habilito despues de llenar la identificacion")

    # ------------------------------------------------------------------ #
    # Listeners de red                                                     #
    # ------------------------------------------------------------------ #

    def _attach_response_listener(self, page: Page, payloads: dict[str, Any]) -> None:
        async def on_response(response: Any) -> None:
            url = response.url
            if response.status >= 400:
                logger.warning("network_response_error status=%s url=%s", response.status, url)
                if "captcha" in url.lower() or "validar" in url.lower():
                    error_payload: dict[str, Any] = {"status": response.status, "url": url}
                    try:
                        body = await response.text()
                        error_payload["body"] = body
                        logger.warning("captcha_error_body status=%s body=%.800s", response.status, body)
                    except Exception:
                        pass
                    payloads["captcha_validation_error"] = error_payload
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
            lambda req: logger.warning("network_request_failed method=%s url=%s failure=%s", req.method, req.url, req.failure),
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

    # ------------------------------------------------------------------ #
    # Utilidades                                                           #
    # ------------------------------------------------------------------ #

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
        except PlaywrightError:
            pass

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
            "browser_validation": await self._browser_validation_state(page),
            "body_text": await self._safe_text_snapshot(page),
        }
        try:
            diagnostics["button_enabled"] = await page.get_by_role("button", name="Consultar").is_enabled(timeout=1000)
        except PlaywrightError:
            diagnostics["button_enabled"] = None
        return diagnostics

    def _classify_response(self, data: EstadoTributarioData | None, html: str) -> str:
        if "no se encuentra en la base de datos" in html.lower():
            return "not_found"
        if data and (data.estado_tributario.resultado or data.permiso_facturacion.vigencia):
            return "ok"
        return "ok"

    def _elapsed_ms(self, started_at: float) -> int:
        return round((time.monotonic() - started_at) * 1000)

    async def _human_type(self, page: Page, field: Any, value: str) -> None:
        await self._human_move_to_locator(page, field)
        await self._human_pause(0.25, 0.9)
        await field.click()
        await field.fill("")

        started_at = time.monotonic()
        min_pause = max(_HUMAN_TYPE_PAUSE_MIN, _HUMAN_TYPE_MIN_SECONDS / max(len(value), 1) * 0.55)
        max_pause = max(_HUMAN_TYPE_PAUSE_MAX, _HUMAN_TYPE_MIN_SECONDS / max(len(value), 1) * 1.35)

        for index, char in enumerate(value):
            await page.keyboard.type(char)
            if index < len(value) - 1:
                await self._human_pause(min_pause, max_pause)

        remaining = _HUMAN_TYPE_MIN_SECONDS - (time.monotonic() - started_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        await self._human_pause(0.25, 0.75)

    async def _human_move_to_locator(self, page: Page, locator: Any) -> None:
        try:
            box = await locator.bounding_box()
        except PlaywrightError:
            box = None
        if not box:
            await self._human_pause(0.15, 0.45)
            return

        target_x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
        steps = random.randint(_HUMAN_MOUSE_STEPS_MIN, _HUMAN_MOUSE_STEPS_MAX)
        await page.mouse.move(target_x, target_y, steps=steps)

    async def _human_pause(self, min_seconds: float, max_seconds: float) -> None:
        await asyncio.sleep(random.uniform(min_seconds, max_seconds))

    async def _browser_validation_state(self, page: Page) -> dict[str, Any]:
        try:
            return await page.evaluate(
                """() => {
                    const state = {
                        userAgent: navigator.userAgent,
                        browserSpecs: navigator.browserSpecs || null,
                        overlays: {},
                    };
                    for (const id of ["noSoportado", "advertenciaNavegador", "disablingDiv"]) {
                        const el = document.getElementById(id);
                        if (!el) {
                            state.overlays[id] = { present: false, visible: false };
                            continue;
                        }
                        const style = window.getComputedStyle(el);
                        const visible = style.display !== "none"
                            && style.visibility !== "hidden"
                            && style.opacity !== "0";
                        state.overlays[id] = {
                            present: true,
                            visible,
                            display: style.display,
                            visibility: style.visibility,
                            opacity: style.opacity,
                        };
                    }
                    return state;
                }"""
            )
        except PlaywrightError:
            return {}

    def _captcha_error_message(self, payloads: dict[str, Any]) -> str | None:
        error = payloads.get("captcha_validation_error")
        if not isinstance(error, dict):
            return None

        body = error.get("body")
        if not isinstance(body, str) or not body:
            return f"El SRI rechazo el token reCAPTCHA. HTTP {error.get('status')}."

        message = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                message = str(parsed.get("mensaje") or message)
                if message.startswith("{"):
                    nested = json.loads(message)
                    if isinstance(nested, dict):
                        message = str(nested.get("mensaje") or message)
        except Exception:
            pass

        return f"El SRI rechazo el token reCAPTCHA: {message}"
