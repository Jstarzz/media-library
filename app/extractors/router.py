from app.extractors.base import ExtractResult
from app.extractors.browser import BrowserExtractor
from app.extractors.generic import GenericExtractor
from app.extractors.pixieset import PixiesetExtractor, is_pixieset_host, looks_like_pixieset
from app.extractors.tools import GalleryDLExtractor, YtDlpExtractor, detect_platform


def merge_results(primary: ExtractResult, secondary: ExtractResult) -> ExtractResult:
    seen = {item.url for item in primary.media}
    for item in secondary.media:
        if item.url not in seen:
            primary.media.append(item)
            seen.add(item.url)

    primary.title = primary.title or secondary.title
    primary.author = primary.author or secondary.author
    primary.caption = primary.caption or secondary.caption
    primary.description = primary.description or secondary.description
    primary.published_at = primary.published_at or secondary.published_at
    primary.extracted_text = primary.extracted_text or secondary.extracted_text
    primary.canonical_url = primary.canonical_url or secondary.canonical_url
    if secondary.extractor not in primary.extractor:
        primary.extractor = f"{primary.extractor}+{secondary.extractor}"
    primary.warnings.extend(secondary.warnings)
    return primary


class ExtractorRouter:
    def __init__(self):
        self.gallery = GalleryDLExtractor()
        self.video = YtDlpExtractor()
        self.generic = GenericExtractor()
        self.browser = BrowserExtractor()
        self.pixieset = PixiesetExtractor()

    async def _generic_layered(self, url: str, errors: list[str]) -> ExtractResult:
        static_result = None
        try:
            static_result = await self.generic.extract(url)
            # Photographer galleries on custom domains: the static page only
            # exposes a cover image, but its CDN gives it away.
            if looks_like_pixieset(static_result):
                try:
                    full = await self.pixieset.extract(url)
                    if full.media:
                        return full
                except Exception as exc:
                    errors.append(f"{self.pixieset.name}: {exc}")
            if len(static_result.media) >= 2:
                if errors:
                    static_result.warnings.extend(errors)
                return static_result
        except Exception as exc:
            errors.append(f"{self.generic.name}: {exc}")

        try:
            rendered = await self.browser.extract(url)
            if static_result:
                result = merge_results(static_result, rendered)
            else:
                result = rendered
            if errors:
                result.warnings.extend(errors)
            return result
        except Exception as exc:
            errors.append(f"{self.browser.name}: {exc}")

        if static_result and (static_result.media or static_result.extracted_text or static_result.caption):
            static_result.warnings.extend(errors)
            return static_result
        raise ValueError("; ".join(errors) or "No extractor succeeded")

    async def extract(self, url: str, generic_only: bool = False) -> ExtractResult:
        errors: list[str] = []
        if generic_only:
            return await self._generic_layered(url, errors)

        platform = detect_platform(url)
        extractors = []
        if is_pixieset_host(url):
            extractors.append(self.pixieset)
        elif platform in {"facebook", "instagram"}:
            extractors.extend([self.gallery, self.video])
        elif platform in {"youtube", "tiktok"}:
            extractors.append(self.video)

        for extractor in extractors:
            try:
                result = await extractor.extract(url)
                if result.media:
                    if errors:
                        result.warnings.extend(errors)
                    return result
                errors.append(f"{extractor.name}: no downloadable media discovered")
            except Exception as exc:
                errors.append(f"{extractor.name}: {exc}")

        return await self._generic_layered(url, errors)
