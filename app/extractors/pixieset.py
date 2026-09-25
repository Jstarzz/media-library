"""Pixieset client galleries (*.pixieset.com and photographers' custom domains).

A gallery page only renders a screenful of thumbnails, so the generic and
rendered extractors save ~30 low-res previews. Pixieset's own gallery page
loads every photo from a JSON endpoint:

    /client/loadphotos/?cuk=<collection url key>&cid=<collection id>&gs=<set slug>&page=N

That endpoint needs the session cookie the page sets (and many photographer
domains sit behind a Cloudflare check), so the page is opened in Chromium and
the endpoint is called from inside it. Every set and page is walked and each
photo is taken at the largest size Pixieset serves to a visitor.
"""

import asyncio
import json
import re
from urllib.parse import urlparse

from app.config import get_settings
from app.extractors.base import ExtractResult, MediaCandidate
from app.extractors.browser import BROWSER_USER_AGENT, public_only_route
from app.urls import validate_public_url


PIXIESET_IMAGE_HOSTS = ("images.pixieset.com",)
SIZE_KEYS = ("pathXxlarge", "pathXlarge", "pathLarge", "pathMedium")
MAX_PAGES_PER_SET = 100


def is_pixieset_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "pixieset.com" or host.endswith(".pixieset.com")


def looks_like_pixieset(result: ExtractResult | None) -> bool:
    """A custom-domain gallery gives itself away by its image CDN."""
    if not result:
        return False
    return any((urlparse(m.url).hostname or "") in PIXIESET_IMAGE_HOSTS for m in result.media)


def parse_gallery_page(html: str) -> dict:
    """Pull the collection id, url key, set slugs and title out of the page's inline config."""
    cid = re.search(r"collectionId['\"]?\s*:\s*['\"]?(\d+)", html)
    cuk = re.search(r"collectionUrlKey['\"]?\s*:\s*['\"]([^'\"]+)['\"]", html)
    slugs = list(dict.fromkeys(re.findall(r"['\"]slug['\"]\s*:\s*['\"]([^'\"]+)['\"]", html)))
    title = re.search(r"<title>([^<]*)</title>", html, re.I)
    return {
        "cid": cid.group(1) if cid else None,
        "cuk": cuk.group(1).encode().decode("unicode_escape") if cuk else None,
        "sets": slugs or ["highlights"],
        "title": title.group(1).strip() if title else None,
    }


def photo_to_candidate(photo: dict, set_slug: str) -> MediaCandidate | None:
    path = next((photo[k] for k in SIZE_KEYS if photo.get(k)), None)
    if not path:
        return None
    url = "https:" + path if path.startswith("//") else path
    width, height = photo.get("width"), photo.get("height")
    # Pixieset caps delivered size (maxWidth/maxHeight); scale the original
    # dimensions down to what the chosen file actually is.
    cap = max(photo.get("maxWidth") or 0, photo.get("maxHeight") or 0)
    if width and height and cap and max(width, height) > cap:
        ratio = cap / max(width, height)
        width, height = round(width * ratio), round(height * ratio)
    return MediaCandidate(
        url=url,
        media_type="image",
        mime_type="image/jpeg",
        platform_media_id=str(photo.get("id")) if photo.get("id") else None,
        filename=photo.get("name"),
        width=width,
        height=height,
        thumbnail_url=("https:" + photo["pathThumb"]) if str(photo.get("pathThumb", "")).startswith("//") else None,
        alt_text=f"{set_slug}: {photo.get('name')}" if photo.get("name") else None,
    )


class PixiesetExtractor:
    name = "pixieset"

    def supports(self, url: str) -> bool:
        return is_pixieset_host(url)

    async def extract(self, url: str) -> ExtractResult:
        settings = get_settings()
        if not settings.browser_enabled:
            raise ValueError("Pixieset extraction needs the browser (MEDIA_LIBRARY_BROWSER_ENABLED)")
        await asyncio.to_thread(validate_public_url, url)
        from playwright.async_api import async_playwright

        photos_by_set: dict[str, list[dict]] = {}
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            context = await browser.new_context(user_agent=BROWSER_USER_AGENT, viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            await page.route("**/*", public_only_route)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
                meta = {}
                # A Cloudflare interstitial swaps itself for the gallery after a few seconds.
                for _ in range(20):
                    meta = parse_gallery_page(await page.content())
                    if meta["cid"] and meta["cuk"]:
                        break
                    await page.wait_for_timeout(750)
                if not (meta.get("cid") and meta.get("cuk")):
                    raise ValueError("not a Pixieset gallery page (no collectionId)")
                final_url = page.url
                for set_slug in meta["sets"]:
                    photos_by_set[set_slug] = []
                    for page_no in range(1, MAX_PAGES_PER_SET + 1):
                        endpoint = (
                            f"/client/loadphotos/?cuk={meta['cuk']}&cid={meta['cid']}"
                            f"&gs={set_slug}&fk=&page={page_no}"
                        )
                        body = await page.evaluate(
                            "async (u) => (await fetch(u, {headers: {'X-Requested-With': 'XMLHttpRequest'}})).text()",
                            endpoint,
                        )
                        data = json.loads(body)
                        if data.get("status") != "success" or not data.get("content"):
                            break
                        photos_by_set[set_slug].extend(json.loads(data["content"]))
                        if data.get("isLastPage"):
                            break
            finally:
                await page.unroute_all(behavior="ignoreErrors")
                await context.close()
                await browser.close()

        media: list[MediaCandidate] = []
        seen: set[str] = set()
        for set_slug, photos in photos_by_set.items():
            for photo in photos:
                candidate = photo_to_candidate(photo, set_slug)
                if candidate and candidate.url not in seen:
                    seen.add(candidate.url)
                    media.append(candidate)

        counts = ", ".join(f"{slug}: {len(p)}" for slug, p in photos_by_set.items())
        return ExtractResult(
            original_url=url,
            canonical_url=final_url,
            platform="pixieset",
            extractor=self.name,
            title=meta.get("title"),
            description=f"Pixieset gallery sets ({counts})",
            platform_source_id=meta.get("cid"),
            media=media,
        )
