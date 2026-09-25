from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class MediaCandidate:
    url: str
    media_type: str
    mime_type: str | None = None
    platform_media_id: str | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    alt_text: str | None = None


@dataclass
class ExtractResult:
    original_url: str
    canonical_url: str | None
    platform: str
    extractor: str
    title: str | None = None
    author: str | None = None
    caption: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    extracted_text: str | None = None
    platform_source_id: str | None = None
    media: list[MediaCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        value = asdict(self)
        if self.published_at:
            value["published_at"] = self.published_at.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "ExtractResult":
        data = dict(value)
        if data.get("published_at"):
            data["published_at"] = datetime.fromisoformat(data["published_at"])
        data["media"] = [MediaCandidate(**item) for item in data.get("media", [])]
        return cls(**data)


class Extractor(Protocol):
    name: str

    def supports(self, url: str) -> bool: ...
    async def extract(self, url: str) -> ExtractResult: ...
