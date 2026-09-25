import asyncio
import json
import mimetypes
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.extractors.base import ExtractResult, MediaCandidate
from app.extractors.router import ExtractorRouter
from app.models import ContentRecord, IngestJob, IngestJobItem, MediaItem, Source, new_id
from app.services.search import index_source
from app.storage import LocalStorageProvider, extension_for, sha256_file
from app.urls import safe_get


class IngestService:
    def __init__(self):
        self.router = ExtractorRouter()
        self.storage = LocalStorageProvider()
        self._heavy = asyncio.Semaphore(get_settings().scan_concurrency)

    async def run_job(self, job_id: str, generic_only: bool = False) -> None:
        factory = get_session_factory()
        with factory() as db:
            job = db.get(IngestJob, job_id)
            if not job:
                return
            job.status = "scanning"
            db.commit()
            item_ids = [item.id for item in job.items]

        async def scan(item_id: str):
            async with self._heavy:
                with factory() as db:
                    item = db.get(IngestJobItem, item_id)
                    url = item.url
                try:
                    result = await self.router.extract(url, generic_only=generic_only)
                    with factory() as db:
                        item = db.get(IngestJobItem, item_id)
                        item.scan_json = json.dumps(result.to_dict())
                        item.status = "ready"
                        job = db.get(IngestJob, job_id)
                        job.scanned_urls += 1
                        job.found_media += len(result.media)
                        db.commit()
                except Exception as exc:
                    with factory() as db:
                        item = db.get(IngestJobItem, item_id)
                        item.status = "failed"
                        item.error = str(exc)[:4000]
                        job = db.get(IngestJob, job_id)
                        job.scanned_urls += 1
                        db.commit()

        await asyncio.gather(*(scan(item_id) for item_id in item_ids))

        with factory() as db:
            job = db.get(IngestJob, job_id)
            failed = sum(1 for item in job.items if item.status == "failed")
            job.status = "partial" if failed else "ready"
            auto_import = job.auto_import
            db.commit()

        if auto_import:
            await self.import_job(job_id)

    async def import_job(self, job_id: str, selected: dict[str, list[int]] | None = None) -> None:
        factory = get_session_factory()
        with factory() as db:
            job = db.get(IngestJob, job_id)
            if not job:
                return
            job.status = "importing"
            db.commit()
            item_ids = [item.id for item in job.items if item.scan_json]

        imported = 0
        failures = 0
        for item_id in item_ids:
            with factory() as db:
                item = db.get(IngestJobItem, item_id)
                job = db.get(IngestJob, job_id)
                result = ExtractResult.from_dict(json.loads(item.scan_json))
                indexes = selected.get(item_id) if selected else None
            try:
                count = await self._import_result(job.workspace_slug, result, indexes)
                imported += count
                with factory() as db:
                    item = db.get(IngestJobItem, item_id)
                    item.status = "complete"
                    db.commit()
            except Exception as exc:
                failures += 1
                with factory() as db:
                    item = db.get(IngestJobItem, item_id)
                    item.status = "failed"
                    item.error = str(exc)[:4000]
                    db.commit()

        with factory() as db:
            job = db.get(IngestJob, job_id)
            job.imported_media += imported
            job.status = "partial" if failures else "complete"
            db.commit()

    async def _import_result(self, workspace: str, result: ExtractResult, indexes: list[int] | None) -> int:
        factory = get_session_factory()
        with factory() as db:
            source = db.scalar(select(Source).where(Source.workspace_slug == workspace, Source.canonical_url == result.canonical_url))
            if not source:
                source = Source(
                    workspace_slug=workspace, original_url=result.original_url, canonical_url=result.canonical_url,
                    platform=result.platform, platform_source_id=result.platform_source_id, title=result.title,
                    author=result.author, caption=result.caption, description=result.description,
                    published_at=result.published_at, extracted_text=result.extracted_text,
                    extractor=result.extractor, status="importing",
                )
                db.add(source)
                db.flush()
                for content_type, value in (("title", result.title), ("caption", result.caption), ("page_text", result.extracted_text)):
                    if value:
                        db.add(ContentRecord(workspace_slug=workspace, source_id=source.id, content_type=content_type, text=value))
                db.commit()
            source_id = source.id

        wanted = range(len(result.media)) if indexes is None else indexes
        imported = 0
        for index in wanted:
            if index < 0 or index >= len(result.media):
                continue
            candidate = result.media[index]
            try:
                if await self._import_media(workspace, source_id, index, candidate):
                    imported += 1
            except Exception:
                continue

        with factory() as db:
            source = db.get(Source, source_id)
            source.status = "imported"
            index_source(db, source)
            db.commit()
        return imported

    async def _import_media(self, workspace: str, source_id: str, index: int, candidate: MediaCandidate) -> bool:
        factory = get_session_factory()
        with factory() as db:
            if candidate.platform_media_id:
                existing = db.scalar(select(MediaItem).where(MediaItem.workspace_slug == workspace, MediaItem.platform_media_id == candidate.platform_media_id))
                if existing:
                    source = db.get(Source, source_id)
                    if source not in existing.sources:
                        existing.sources.append(source)
                        db.commit()
                    return False

        max_bytes = get_settings().max_media_mb * 1024 * 1024
        response = await safe_get(candidate.url, max_bytes=max_bytes)
        mime = (candidate.mime_type or response.headers.get("content-type", "")).split(";")[0] or None
        ext = extension_for(mime, candidate.url)

        temp = self.storage.workspace_dir(workspace) / "media" / f".download-{source_id}-{index}{ext}"
        temp.write_bytes(response.content)
        digest = sha256_file(temp)

        with factory() as db:
            existing = db.scalar(select(MediaItem).where(MediaItem.workspace_slug == workspace, MediaItem.sha256 == digest))
            source = db.get(Source, source_id)
            if existing:
                temp.unlink(missing_ok=True)
                if source not in existing.sources:
                    existing.sources.append(source)
                    db.commit()
                return False

            media_id = new_id("med")
            final_path = self.storage.media_path(workspace, source_id, index, candidate.url, ext)
            temp.replace(final_path)
            media = MediaItem(
                id=media_id, workspace_slug=workspace, platform_media_id=candidate.platform_media_id,
                media_type=candidate.media_type, mime_type=mime, original_url=candidate.url,
                local_path=str(final_path), filename=final_path.name, original_filename=candidate.filename,
                width=candidate.width, height=candidate.height, duration=int(candidate.duration) if candidate.duration else None,
                file_size=final_path.stat().st_size, alt_text=candidate.alt_text, sha256=digest,
            )
            media.sources.append(source)
            db.add(media)
            db.flush()
            thumb = self.storage.thumbnail_path(workspace, media.id)
            self.storage.make_thumbnail(final_path, thumb, media.media_type)
            if thumb.exists():
                media.thumbnail_path = str(thumb)
            db.commit()
        return True
