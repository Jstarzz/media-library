import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.extractors.base import ExtractResult, MediaCandidate


PLATFORM_HOSTS = {
    "facebook": ("facebook.com", "fb.watch"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
}


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for platform, suffixes in PLATFORM_HOSTS.items():
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
            return platform
    return "web"


def _cookie_file(platform: str) -> Path | None:
    path = get_settings().cookie_dir / f"{platform}.cookies.txt"
    return path if path.exists() else None


async def _run(*args: str, timeout: int = 45) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError(f"{args[0]} timed out")
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise ValueError(f"{args[0]} failed: {message[0]}")
    return stdout.decode(errors="replace")


class YtDlpExtractor:
    name = "yt-dlp"

    def supports(self, url: str) -> bool:
        return detect_platform(url) in {"youtube", "tiktok", "facebook", "instagram"}

    async def extract(self, url: str) -> ExtractResult:
        platform = detect_platform(url)
        args = ["yt-dlp", "--dump-single-json", "--skip-download", "--no-warnings"]
        cookie = _cookie_file(platform)
        if cookie:
            args.extend(["--cookies", str(cookie)])
        args.append(url)
        payload = json.loads(await _run(*args))

        entries = payload.get("entries") or [payload]
        media: list[MediaCandidate] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            formats = item.get("formats") or []
            candidates = [f for f in formats if isinstance(f, dict) and f.get("url")]
            best = None
            for f in candidates:
                if f.get("vcodec") not in {None, "none"}:
                    if best is None or (f.get("height") or 0) > (best.get("height") or 0):
                        best = f
            direct = (best or item).get("url")
            if direct:
                media.append(MediaCandidate(
                    url=direct,
                    media_type="video",
                    mime_type=(best or item).get("mime_type"),
                    platform_media_id=str(item.get("id") or "") or None,
                    filename=(item.get("title") or item.get("id") or "video") + ".mp4",
                    width=(best or item).get("width"),
                    height=(best or item).get("height"),
                    duration=item.get("duration"),
                    thumbnail_url=item.get("thumbnail"),
                ))
        timestamp = payload.get("timestamp")
        published = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None
        return ExtractResult(
            original_url=url,
            canonical_url=payload.get("webpage_url") or url,
            platform=platform,
            extractor=self.name,
            title=payload.get("title"),
            author=payload.get("uploader") or payload.get("channel"),
            caption=payload.get("description"),
            description=payload.get("description"),
            published_at=published,
            platform_source_id=str(payload.get("id") or "") or None,
            media=media,
        )


class GalleryDLExtractor:
    name = "gallery-dl"

    def supports(self, url: str) -> bool:
        return detect_platform(url) in {"facebook", "instagram"}

    async def extract(self, url: str) -> ExtractResult:
        platform = detect_platform(url)
        args = ["gallery-dl", "--dump-json"]
        cookie = _cookie_file(platform)
        if cookie:
            args.extend(["--cookies", str(cookie)])
        args.append(url)
        raw = await _run(*args)
        media: list[MediaCandidate] = []
        metadata: dict = {}
        seen: set[str] = set()

        def inspect(node):
            nonlocal metadata
            if isinstance(node, dict):
                if not metadata:
                    metadata = node
                direct = node.get("url") or node.get("file_url") or node.get("download_url")
                if isinstance(direct, str) and direct.startswith(("http://", "https://")) and direct not in seen:
                    ext = (node.get("extension") or "").lower()
                    media_type = "video" if ext in {"mp4", "webm", "mov"} else "image"
                    media.append(MediaCandidate(
                        url=direct, media_type=media_type,
                        platform_media_id=str(node.get("id") or node.get("media_id") or "") or None,
                        filename=node.get("filename"), width=node.get("width"), height=node.get("height"),
                    ))
                    seen.add(direct)
                for value in node.values(): inspect(value)
            elif isinstance(node, list):
                for value in node: inspect(value)

        for line in raw.splitlines():
            try: inspect(json.loads(line))
            except json.JSONDecodeError: continue

        return ExtractResult(
            original_url=url,
            canonical_url=url,
            platform=platform,
            extractor=self.name,
            title=metadata.get("title"),
            author=metadata.get("author") or metadata.get("username") or metadata.get("owner_name"),
            caption=metadata.get("description") or metadata.get("caption") or metadata.get("text"),
            platform_source_id=str(metadata.get("id") or metadata.get("post_id") or "") or None,
            media=media,
        )
