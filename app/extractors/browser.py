import asyncio
from urllib.parse import urlparse

from app.config import get_settings
from app.extractors.base import ExtractResult, MediaCandidate
from app.extractors.generic import extract_html
from app.urls import validate_public_url


MEDIA_PREFIXES = ("image/", "video/", "audio/")
BAD_URL_HINTS = ("favicon", "sprite", "logo", "icon-", "/icons/", "tracking", "pixel")


def score_network_candidate(url: str, mime_type: str, content_length: int | None, resource_type: str) -> int:
    mime_type = mime_type.lower()
    if not mime_type.startswith(MEDIA_PREFIXES):
        return -100

    score = 2
    if resource_type in {"image", "media"}:
        score += 1
    if content_length is not None:
        if content_length < 8_000:
            score -= 3
        elif content_length >= 25_000:
            score += 1
    lower_url = url.lower()
    if any(hint in lower_url for hint in BAD_URL_HINTS):
        score -= 3
    return score


class BrowserExtractor:
    name = "playwright"

    def supports(self, url: str) -> bool:
        return get_settings().browser_enabled

    async def extract(self, url: str) -> ExtractResult:
        settings = get_settings()
        if not settings.browser_enabled:
            raise ValueError("Browser discovery is disabled")
        validate_public_url(url)

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ValueError("Playwright is not installed") from exc

        network_media: dict[str, MediaCandidate] = {}
        request_tasks: set[asyncio.Task] = set()
        host_cache: dict[tuple[str, str, int | None], bool] = {}

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            context = await browser.new_context(
                user_agent="MediaLibrary/0.1 (+internal media discovery)",
                viewport={"width": 1440, "height": 1000},
            )
            page = await context.new_page()

            async def guard(route):
                request_url = route.request.url
                parsed = urlparse(request_url)
                if parsed.scheme in {"data", "blob", "about"}:
                    await route.continue_()
                    return
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    await route.abort()
                    return

                key = (parsed.scheme, parsed.hostname.lower(), parsed.port)
                allowed = host_cache.get(key)
                if allowed is None:
                    try:
                        validate_public_url(request_url)
                        allowed = True
                    except ValueError:
                        allowed = False
                    host_cache[key] = allowed

                if allowed:
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", guard)

            async def capture(response):
                try:
                    headers = await response.all_headers()
                    mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    raw_length = headers.get("content-length")
                    length = int(raw_length) if raw_length and raw_length.isdigit() else None
                    resource_type = response.request.resource_type
                    if score_network_candidate(response.url, mime, length, resource_type) < 2:
                        return
                    kind = mime.split("/", 1)[0]
                    if kind not in {"image", "video", "audio"}:
                        return
                    network_media.setdefault(
                        response.url,
                        MediaCandidate(
                            url=response.url,
                            media_type=kind,
                            mime_type=mime or None,
                        ),
                    )
                except Exception:
                    return

            def on_response(response):
                task = asyncio.create_task(capture(response))
                request_tasks.add(task)
                task.add_done_callback(request_tasks.discard)

            page.on("response", on_response)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
                await page.wait_for_timeout(900)
                for _ in range(max(0, settings.browser_scrolls)):
                    await page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 800))")
                    await page.wait_for_timeout(450)
                html = await page.content()
                final_url = page.url
                if request_tasks:
                    await asyncio.gather(*list(request_tasks), return_exceptions=True)
            finally:
                await context.close()
                await browser.close()

        rendered = extract_html(final_url, html)
        rendered.extractor = self.name

        seen = {item.url for item in rendered.media}
        for item in network_media.values():
            if item.url not in seen:
                rendered.media.append(item)
                seen.add(item.url)

        return rendered
