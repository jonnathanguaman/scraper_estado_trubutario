import asyncio
import logging
from pathlib import Path

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, Page

from app.config import Settings

logger = logging.getLogger(__name__)


class SriBrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._camoufox: AsyncCamoufox | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._browser is not None

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def start(self) -> bool:
        if self._browser is not None:
            logger.debug("browser_session_reuse")
            return False

        logger.info(
            "browser_session_start headless=%s profile_dir=%s timeout_ms=%s",
            self.settings.sri_headless,
            self.settings.sri_profile_dir,
            self.settings.sri_timeout_ms,
        )
        self._camoufox = AsyncCamoufox(
            headless=self.settings.sri_headless,
            os="windows",
            locale="es-EC",
        )
        self._browser = await self._camoufox.__aenter__()
        logger.info("browser_session_started")
        return True

    async def stop(self) -> bool:
        was_started = self._browser is not None
        logger.info("browser_session_stop requested started=%s", was_started)
        if self._camoufox is not None:
            try:
                await self._camoufox.__aexit__(None, None, None)
            except Exception:
                logger.debug("browser_stop_error", exc_info=True)
            self._camoufox = None
            self._browser = None
        logger.info("browser_session_stopped")
        return was_started

    async def page(self) -> Page:
        await self.start()
        assert self._browser is not None
        logger.debug("browser_page_new")
        page = await self._browser.new_page(
            viewport={"width": 1366, "height": 900},
            locale="es-EC",
        )
        page.set_default_timeout(self.settings.sri_timeout_ms)
        return page

    def profile_dir(self) -> Path:
        return self.settings.sri_profile_dir
