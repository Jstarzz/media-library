import json
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.extractors.base import ExtractResult, MediaCandidate
from app.urls import normalize_url, safe_get


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg"}


def _kind(url: str, mime: str | None = None) -> str | None:
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTS:
        if path.endswith(ext): return "image"
    for ext in VIDEO_EXTS:
        if path.endswith(ext): return "video"
    for ext in AUDIO_EXTS:
        if path.endswith(ext): return "audio"
    return None


def _best_srcset(value: str) -> str | None:
    candidates = []
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        score = 0
        if len(bits) > 1:
            raw = bits[-1].lower()
            try:
                score = int(float(raw.rstrip("wx")))
            except ValueError:
                pass
        candidates.append((score, bits[0]))
    return max(candidates, default=(0, None))[1]


def extract_html(url: str, html: str) -> ExtractResult:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string.strip() if soup.title and soup.title.string else None)
    canonical = soup.select_one('link[rel="canonical"]')
    canonical_url = urljoin(url, canonical.get("href")) if canonical and canonical.get("href") else normalize_url(url)

    def meta(*keys: tuple[str, str]) -> str | None:
        for attr, value in keys:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    description = meta(("property", "og:description"), ("name", "description"), ("name", "twitter:description"))
    author = meta(("name", "author"), ("property", "article:author"))
    date_raw = meta(("property", "article:published_time"), ("name", "date"))
    published_at = None
    if date_raw:
        try:
            published_at = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        except ValueError:
            pass

    seen: set[str] = set()
    media: list[MediaCandidate] = []

    def add(raw: str | None, media_type: str | None = None, mime: str | None = None, alt: str | None = None):
        if not raw:
            return
        resolved = urljoin(url, raw.strip())
        kind = media_type or _kind(resolved, mime)
        if not kind or resolved in seen or resolved.startswith("data:"):
            return
        seen.add(resolved)
        media.append(MediaCandidate(url=resolved, media_type=kind, mime_type=mime, alt_text=alt))

    for prop, kind in (("og:image", "image"), ("twitter:image", "image"), ("og:video", "video"), ("twitter:player", "video")):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            add(tag.get("content"), kind)

    for img in soup.find_all("img"):
        src = _best_srcset(img.get("srcset", "")) or img.get("src") or img.get("data-src")
        width = img.get("width")
        height = img.get("height")
        try:
            if width and height and int(width) <= 48 and int(height) <= 48:
                continue
        except ValueError:
            pass
        add(src, "image", alt=img.get("alt"))

    for tag in soup.find_all(["source", "video", "audio"]):
        src = tag.get("src")
        if not src and tag.get("srcset"):
            src = _best_srcset(tag.get("srcset"))
        mime = tag.get("type")
        forced = "video" if tag.name == "video" else "audio" if tag.name == "audio" else None
        add(src, forced, mime)
        if tag.name == "video":
            add(tag.get("poster"), "image")

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                typ = node.get("@type")
                if typ in {"ImageObject", "VideoObject"}:
                    add(node.get("contentUrl") or node.get("url"), "image" if typ == "ImageObject" else "video")
                    add(node.get("thumbnailUrl"), "image")
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)

    main = soup.find("article") or soup.find("main") or soup.body
    text = " ".join(main.stripped_strings)[:120_000] if main else None

    return ExtractResult(
        original_url=url,
        canonical_url=canonical_url,
        platform="web",
        extractor="generic-html",
        title=title,
        author=author,
        caption=description,
        description=description,
        published_at=published_at,
        extracted_text=text,
        media=media,
    )


class GenericExtractor:
    name = "generic-html"

    def supports(self, url: str) -> bool:
        return True

    async def extract(self, url: str) -> ExtractResult:
        response = await safe_get(url, accept="text/html,application/xhtml+xml")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            raise ValueError(f"Generic extractor expected HTML, got {content_type or 'unknown content type'}")
        return extract_html(str(response.url), response.text)
