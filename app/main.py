from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request

from app.config import get_settings
from app.logging_config import configure_logging
from app.schemas import BrowserSessionResponse, ConsultaRequest, ConsultaResponse, HealthResponse
from app.sri.browser import SriBrowserManager
from app.sri.scraper import SriScraper

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)
browser_manager = SriBrowserManager(settings)
scraper = SriScraper(browser_manager, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await browser_manager.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.monotonic()
    logger.info("http_request_start method=%s path=%s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http_request_error method=%s path=%s elapsed_ms=%s",
            request.method,
            request.url.path,
            round((time.monotonic() - started_at) * 1000),
        )
        raise
    logger.info(
        "http_request_end method=%s path=%s status=%s elapsed_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        round((time.monotonic() - started_at) * 1000),
    )
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        playwright_available=True,
        browser_started=browser_manager.started,
    )


@app.post("/api/v1/browser/session/start", response_model=BrowserSessionResponse)
async def start_browser_session() -> BrowserSessionResponse:
    started = await browser_manager.start()
    return BrowserSessionResponse(
        status="started" if started else "already_started",
        profile_dir=str(browser_manager.profile_dir()),
    )


@app.post("/api/v1/browser/session/close", response_model=BrowserSessionResponse)
async def close_browser_session() -> BrowserSessionResponse:
    await browser_manager.stop()
    return BrowserSessionResponse(status="closed", profile_dir=str(browser_manager.profile_dir()))


@app.post("/api/v1/estado-tributario/consultar", response_model=ConsultaResponse, response_model_exclude_none=True)
async def consultar_estado_tributario(request: ConsultaRequest) -> ConsultaResponse:
    return await scraper.consultar(request)

