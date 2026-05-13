import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config import Settings


class SriBrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._context is not None

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def start(self) -> bool:
        if self._context is not None:
            return False

        self.settings.sri_profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.settings.sri_profile_dir),
            headless=self.settings.sri_headless,
            viewport={"width": 1366, "height": 900},
            locale="es-EC",
            timezone_id="America/Guayaquil",
            args=["--disable-dev-shm-usage"],
        )
        self._context.set_default_timeout(self.settings.sri_timeout_ms)
        return True

    async def stop(self) -> bool:
        was_started = self._context is not None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        return was_started

    async def page(self) -> Page:
        await self.start()
        assert self._context is not None
        pages = self._context.pages
        if pages:
            return pages[0]
        return await self._context.new_page()

    def profile_dir(self) -> Path:
        return self.settings.sri_profile_dir

