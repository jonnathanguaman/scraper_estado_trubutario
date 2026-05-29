import asyncio
import logging
import subprocess
import sys
import urllib.request
from pathlib import Path

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config import Settings

logger = logging.getLogger(__name__)


class SriBrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._camoufox: AsyncCamoufox | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | BrowserContext | None = None
        self._chrome_process: subprocess.Popen[bytes] | None = None
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

        if self.settings.sri_browser_backend == "chrome_cdp":
            await self._start_chrome_cdp()
            return True

        if self.settings.sri_browser_backend != "camoufox":
            raise ValueError(f"Backend de navegador no soportado: {self.settings.sri_browser_backend}")

        logger.info(
            "browser_session_start headless=%s profile_dir=%s persistent_context=%s timeout_ms=%s",
            self.settings.sri_headless,
            self.settings.sri_profile_dir,
            True,
            self.settings.sri_timeout_ms,
        )
        self.settings.sri_profile_dir.mkdir(parents=True, exist_ok=True)
        self._camoufox = AsyncCamoufox(
            headless=self.settings.sri_headless,
            os="windows",
            locale="es-EC",
            humanize=True,
            persistent_context=True,
            user_data_dir=str(self.settings.sri_profile_dir),
            viewport={"width": 1366, "height": 900},
        )
        self._browser = await self._camoufox.__aenter__()
        logger.info("browser_session_started")
        return True

    async def _start_chrome_cdp(self) -> None:
        chrome_path = self._chrome_executable()
        profile_dir = self.settings.sri_chrome_profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "browser_session_start backend=chrome_cdp chrome_path=%s profile_dir=%s port=%s timeout_ms=%s",
            chrome_path,
            profile_dir,
            self.settings.sri_cdp_port,
            self.settings.sri_timeout_ms,
        )
        chrome_args = [
            str(chrome_path),
            f"--remote-debugging-port={self.settings.sri_cdp_port}",
            f"--user-data-dir={profile_dir.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-default-apps",
            "--window-size=1366,900",
        ]
        self._chrome_process = await asyncio.to_thread(
            subprocess.Popen,
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await self._wait_for_cdp()
        self._playwright = await async_playwright().start()
        browser = await self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.settings.sri_cdp_port}"
        )
        self._browser = browser.contexts[0] if browser.contexts else await browser.new_context()
        logger.info("browser_session_started backend=chrome_cdp")

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
        if self._playwright is not None:
            try:
                if isinstance(self._browser, BrowserContext):
                    await self._browser.close()
            except Exception:
                logger.debug("browser_context_close_error", exc_info=True)
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("playwright_stop_error", exc_info=True)
            self._playwright = None
            self._browser = None
        if self._chrome_process is not None:
            await self._kill_chrome(self._chrome_process)
            self._chrome_process = None
        logger.info("browser_session_stopped")
        return was_started

    async def _kill_chrome(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            if sys.platform == "win32":
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                await asyncio.to_thread(proc.terminate)
                await asyncio.to_thread(proc.wait, 5)
        except Exception:
            logger.debug("chrome_process_stop_error", exc_info=True)

    async def page(self) -> Page:
        await self.start()
        assert self._browser is not None
        if isinstance(self._browser, BrowserContext) and self._browser.pages:
            page = self._browser.pages[0]
            logger.debug("browser_page_reuse existing_pages=%s", len(self._browser.pages))
        else:
            page = await self._browser.new_page()
            logger.debug("browser_page_new")
        page.set_default_timeout(self.settings.sri_timeout_ms)
        return page

    def profile_dir(self) -> Path:
        if self.settings.sri_browser_backend == "chrome_cdp":
            return self.settings.sri_chrome_profile_dir
        return self.settings.sri_profile_dir

    def _chrome_executable(self) -> Path:
        if self.settings.sri_chrome_path:
            return self.settings.sri_chrome_path
        candidates = [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError("No se encontro chrome.exe. Configure SRI_CHROME_PATH.")

    async def _wait_for_cdp(self) -> None:
        url = f"http://127.0.0.1:{self.settings.sri_cdp_port}/json/version"
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            try:
                await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=1).read())
                return
            except Exception:
                await asyncio.sleep(0.25)
        raise TimeoutError(f"Chrome CDP no respondio en {url}")
