from app.extractors.base import ExtractResult
from app.extractors.generic import GenericExtractor
from app.extractors.tools import GalleryDLExtractor, YtDlpExtractor, detect_platform


class ExtractorRouter:
    def __init__(self):
        self.gallery = GalleryDLExtractor()
        self.video = YtDlpExtractor()
        self.generic = GenericExtractor()

    async def extract(self, url: str, generic_only: bool = False) -> ExtractResult:
        if generic_only:
            return await self.generic.extract(url)

        platform = detect_platform(url)
        errors = []
        extractors = []
        if platform in {"facebook", "instagram"}:
            extractors.extend([self.gallery, self.video])
        elif platform in {"youtube", "tiktok"}:
            extractors.append(self.video)
        extractors.append(self.generic)

        for extractor in extractors:
            try:
                result = await extractor.extract(url)
                if result.media or result.extracted_text or result.caption:
                    if errors:
                        result.warnings.extend(errors)
                    return result
                errors.append(f"{extractor.name}: no useful media/content")
            except Exception as exc:
                errors.append(f"{extractor.name}: {exc}")

        raise ValueError("; ".join(errors) or "No extractor succeeded")
