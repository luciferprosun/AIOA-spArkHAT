from __future__ import annotations

import time
from pathlib import Path

try:
    from playwright.sync_api import BrowserContext, Page, TimeoutError, sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when Playwright is absent
    BrowserContext = Page = object  # type: ignore[assignment]
    TimeoutError = RuntimeError  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False


class BrowserBridge:
    """Persistent Playwright bridge kept alive across agent actions."""

    def __init__(
        self,
        user_data_dir: Path,
        screenshots_dir: Path,
        headless: bool = True,
        timeout_ms: int = 15000,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.screenshots_dir = screenshots_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.last_selector: str | None = None

    def browser_start(self) -> dict:
        """Legacy helper; public Core routes remain disabled pending certification."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("MANAGED_BROWSER_UNAVAILABLE")
        if self.context is not None:
            self._ensure_page()
            return self._state_message("Browser session already running.")
        try:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            self.playwright = sync_playwright().start()
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 900},
                accept_downloads=False,
                chromium_sandbox=True,
            )
            self.context.set_default_timeout(self.timeout_ms)
            if len(self.context.pages) > 1:
                raise RuntimeError("BROWSER_PAGE_DRIFT")
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self._wait_for_page_ready(self.page)
            return self._state_message("Browser session started.")
        except Exception:
            for resource in (self.context, self.playwright):
                if resource is not None:
                    try:
                        resource.close() if resource is self.context else resource.stop()
                    except Exception:
                        pass
            self.context = self.page = self.playwright = None
            self.last_selector = None
            raise RuntimeError("BROWSER_START_FAILED") from None

    def browser_open(self, url: str) -> dict:
        """Open a URL in the current page."""
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._wait_for_page_ready(page)
        self.last_selector = None
        return self._state_message(f"Opened {url}")

    def browser_click(self, selector: str) -> dict:
        """Click a visible element with retries and post-click waits."""
        page = self._ensure_page()
        locator = self._find_selector(page, selector)
        locator.click(timeout=self.timeout_ms)
        page.wait_for_timeout(350)
        self._wait_for_page_ready(page)
        self.last_selector = selector
        return self._state_message(f"Clicked {selector}")

    def browser_type(self, selector: str, text: str) -> dict:
        """Type or fill text into an input field."""
        page = self._ensure_page()
        locator = self._find_selector(page, selector)
        try:
            locator.fill(text, timeout=self.timeout_ms)
            locator.evaluate("element => element.focus()")
        except TimeoutError:
            locator.evaluate("element => element.focus()")
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(text, delay=25)
        self.last_selector = selector
        return self._state_message(f"Typed into {selector}")

    def browser_press(self, key: str) -> dict:
        """Press one keyboard key on the active page."""
        page = self._ensure_page()
        if self.last_selector:
            try:
                locator = self._find_selector(page, self.last_selector)
                locator.press(key, timeout=self.timeout_ms)
            except TimeoutError:
                page.keyboard.press(key)
        else:
            page.keyboard.press(key)
        page.wait_for_timeout(300)
        self._wait_for_page_ready(page)
        return self._state_message(f"Pressed {key}")

    def browser_read_html(self) -> dict:
        """Return full HTML for the current page."""
        page = self._ensure_page()
        html = page.content()
        return {
            **self._state_message("Read current page HTML."),
            "html": html,
        }

    def browser_get_visible_text(self) -> dict:
        """Return visible body text from the current page."""
        page = self._ensure_page()
        text = page.locator("body").inner_text(timeout=self.timeout_ms)
        return {
            **self._state_message("Read visible page text."),
            "text": text,
        }

    def browser_screenshot(self, path: str | None = None) -> dict:
        """Save a screenshot of the current page."""
        page = self._ensure_page()
        if path:
            screenshot_path = Path(path).expanduser()
            if not screenshot_path.is_absolute():
                screenshot_path = self.screenshots_dir / screenshot_path
        else:
            timestamp = int(time.time() * 1000)
            screenshot_path = self.screenshots_dir / f"screenshot_{timestamp}.png"

        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            **self._state_message(f"Saved screenshot to {screenshot_path}"),
            "screenshot_path": str(screenshot_path),
        }

    def browser_current_url(self) -> dict:
        """Return the current page URL."""
        page = self._ensure_page()
        return {
            **self._state_message("Read current browser URL."),
            "current_url": page.url,
        }

    def browser_close(self) -> dict:
        """Close the persistent browser session cleanly."""
        if self.context is not None:
            self.context.close()
        if self.playwright is not None:
            self.playwright.stop()
        self.context = None
        self.page = None
        self.playwright = None
        self.last_selector = None
        return {
            "success": True,
            "message": "Browser session closed.",
            "current_url": "",
            "open_tabs": [],
        }

    # -----------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------
    def _ensure_page(self) -> Page:
        if self.context is None:
            self.browser_start()
        assert self.context is not None

        if (self.page is not None and not self.page.is_closed()
                and len(self.context.pages) == 1 and self.context.pages[0] is self.page):
            return self.page

        raise RuntimeError("BROWSER_PAGE_DRIFT")

    def _wait_for_page_ready(self, page: Page) -> None:
        for state in ("domcontentloaded", "load"):
            try:
                page.wait_for_load_state(state, timeout=self.timeout_ms)
            except TimeoutError:
                pass
        page.wait_for_timeout(250)

    def _find_selector(self, page: Page, selector: str):
        last_error: Exception | None = None
        for _ in range(3):
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=self.timeout_ms)
                return locator
            except TimeoutError as error:
                last_error = error
                page.wait_for_timeout(400)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Selector not found: {selector}")

    def _state_message(self, message: str) -> dict:
        page = self.page
        current_url = ""
        if page is not None and not page.is_closed():
            current_url = page.url
        tabs = []
        if self.context is not None:
            tabs = [candidate.url for candidate in self.context.pages if not candidate.is_closed()]
        return {
            "success": True,
            "message": message,
            "current_url": current_url,
            "open_tabs": tabs,
        }



_BROWSER_BRIDGE: BrowserBridge | None = None


def configure_browser_bridge(
    user_data_dir: Path,
    screenshots_dir: Path,
    headless: bool = True,
    timeout_ms: int = 15000,
) -> None:
    """Bind the module-level browser bridge used by tool functions."""
    global _BROWSER_BRIDGE
    _BROWSER_BRIDGE = BrowserBridge(
        user_data_dir=user_data_dir,
        screenshots_dir=screenshots_dir,
        headless=headless,
        timeout_ms=timeout_ms,
    )


def get_browser_bridge() -> BrowserBridge:
    """Return the configured browser bridge."""
    if _BROWSER_BRIDGE is None:
        raise RuntimeError("Browser bridge is not configured.")
    return _BROWSER_BRIDGE


def browser_start() -> dict:
    return get_browser_bridge().browser_start()


def browser_open(url: str) -> dict:
    return get_browser_bridge().browser_open(url)


def browser_click(selector: str) -> dict:
    return get_browser_bridge().browser_click(selector)


def browser_type(selector: str, text: str) -> dict:
    return get_browser_bridge().browser_type(selector, text)


def browser_press(key: str) -> dict:
    return get_browser_bridge().browser_press(key)


def browser_read_html() -> dict:
    return get_browser_bridge().browser_read_html()


def browser_get_visible_text() -> dict:
    return get_browser_bridge().browser_get_visible_text()


def browser_screenshot(path: str | None = None) -> dict:
    return get_browser_bridge().browser_screenshot(path)


def browser_close() -> dict:
    return get_browser_bridge().browser_close()


def browser_current_url() -> dict:
    return get_browser_bridge().browser_current_url()
