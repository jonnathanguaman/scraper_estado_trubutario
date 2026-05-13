from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.schemas import BrowserSessionResponse, ConsultaRequest, ConsultaResponse, HealthResponse
from app.sri.browser import SriBrowserManager
from app.sri.scraper import SriScraper

settings = get_settings()
browser_manager = SriBrowserManager(settings)
scraper = SriScraper(browser_manager, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await browser_manager.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


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


@app.post("/api/v1/estado-tributario/consultar", response_model=ConsultaResponse)
async def consultar_estado_tributario(request: ConsultaRequest) -> ConsultaResponse:
    return await scraper.consultar(request)

