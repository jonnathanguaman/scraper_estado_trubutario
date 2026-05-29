from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SRI_SITE_KEY = "6LdukTQsAAAAAIcciM4GZq4ibeyplUhmWvlScuQE"
SRI_WEBSITE_URL = "https://srienlinea.sri.gob.ec"
SRI_PAGE_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/SriDeclaracionesWeb/EstadoTributario/Consultas/consultaEstadoTributario"
SRI_RECAPTCHA_ACTION = "estado_tributario_consulta"
SRI_RECAPTCHA_TASK_TYPE = "ReCaptchaV3EnterpriseTaskProxyless"
SRI_RECAPTCHA_MIN_SCORE = 0.5


@dataclass(frozen=True)
class RecaptchaSolution:
    token: str
    user_agent: str | None = None
    sec_ch_ua: str | None = None


def build_capsolver_task(
    *,
    anchor: str | None = None,
    reload: str | None = None,
) -> dict[str, object]:
    task: dict[str, object] = {
        "type": SRI_RECAPTCHA_TASK_TYPE,
        "websiteURL": SRI_WEBSITE_URL,
        "websiteKey": SRI_SITE_KEY,
        "pageAction": SRI_RECAPTCHA_ACTION,
        "minScore": SRI_RECAPTCHA_MIN_SCORE,
    }
    if anchor:
        task["anchor"] = anchor
    if reload:
        task["reload"] = reload
    return task


async def solve_with_twocaptcha(api_key: str) -> RecaptchaSolution:
    from twocaptcha import TwoCaptcha

    logger.info("twocaptcha_start site_key=%s action=%s", SRI_SITE_KEY[:12], SRI_RECAPTCHA_ACTION)

    def _solve() -> dict:  # type: ignore[type-arg]
        solver = TwoCaptcha(api_key)
        return solver.recaptcha(
            sitekey=SRI_SITE_KEY,
            url=SRI_PAGE_URL,
            version="v3",
            enterprise=1,
            action=SRI_RECAPTCHA_ACTION,
            score=SRI_RECAPTCHA_MIN_SCORE,
        )

    result = await asyncio.to_thread(_solve)
    token: str = result["code"]
    logger.info("twocaptcha_solved token_length=%s", len(token))
    return RecaptchaSolution(token=token)


async def solve_recaptcha_enterprise(
    api_key: str,
    *,
    log_token: bool = False,
    anchor: str | None = None,
    reload: str | None = None,
) -> str:
    solution = await solve_recaptcha_enterprise_with_metadata(
        api_key,
        log_token=log_token,
        anchor=anchor,
        reload=reload,
    )
    return solution.token


async def solve_recaptcha_enterprise_with_metadata(
    api_key: str,
    *,
    log_token: bool = False,
    anchor: str | None = None,
    reload: str | None = None,
) -> RecaptchaSolution:
    import capsolver

    capsolver.api_key = api_key
    task = build_capsolver_task(anchor=anchor, reload=reload)
    logger.info(
        "capsolver_start task_type=%s site_key=%s action=%s min_score=%.1f has_anchor=%s has_reload=%s",
        SRI_RECAPTCHA_TASK_TYPE,
        SRI_SITE_KEY[:12],
        SRI_RECAPTCHA_ACTION,
        SRI_RECAPTCHA_MIN_SCORE,
        bool(anchor),
        bool(reload),
    )

    solution = await asyncio.to_thread(
        capsolver.solve,
        task,
    )

    token: str = solution["gRecaptchaResponse"]
    user_agent = solution.get("userAgent")
    sec_ch_ua = solution.get("secChUa")
    logger.info(
        "capsolver_solved token_length=%s has_user_agent=%s has_sec_ch_ua=%s has_session_cookie=%s",
        len(token),
        bool(user_agent),
        bool(sec_ch_ua),
        bool(solution.get("recaptcha-ca-t")),
    )
    if log_token:
        logger.warning("capsolver_token token=%s", token)
    return RecaptchaSolution(
        token=token,
        user_agent=user_agent if isinstance(user_agent, str) else None,
        sec_ch_ua=sec_ch_ua if isinstance(sec_ch_ua, str) else None,
    )
