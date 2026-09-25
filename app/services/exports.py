import json
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Collection, ExportJob, MediaItem, Source
from app.storage import LocalStorageProvider, safe_filename


def _source_metadata(source: Source | None) -> dict:
    if not source:
        return {}
    return {
        "id": source.id,
        "source_url": source.original_url,
        "canonical_url": source.canonical_url,
        "platform": source.platform,
        "caption": source.caption,
        "title": source.title,
        "author": source.author,
        "date": source.published_at.isoformat() if source.published_at else None,
    }


def create_export(
    db: Session,
    workspace: str,
    *,
    media_ids: list[str] | None = None,
    collection_id: str | None = None,
) -> ExportJob:
    stmt = (
        select(MediaItem)
        .options(selectinload(MediaItem.sources))
        .where(MediaItem.workspace_slug == workspace)
        .order_by(MediaItem.created_at)
    )

    if collection_id:
        collection = db.get(Collection, collection_id)
        if not collection or collection.workspace_slug != workspace:
            raise ValueError("Collection not found in workspace")
        stmt = stmt.where(MediaItem.collections.any(Collection.id == collection_id))

    if media_ids:
        stmt = stmt.where(MediaItem.id.in_(media_ids))

    media = list(db.scalars(stmt).unique())
    if not media:
        raise ValueError("No media selected for export")

    export = ExportJob(workspace_slug=workspace, local_path="", media_count=len(media))
    db.add(export)
    db.flush()

    storage = LocalStorageProvider()
    export_dir = storage.workspace_dir(workspace) / "exports"
    export_path = export_dir / f"{export.id}.zip"
    manifest = {"workspace": workspace, "export_id": export.id, "media": []}
    source_metadata_written: set[str] = set()
    source_indexes: dict[str, int] = {}

    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in media:
            source = item.sources[0] if item.sources else None
            source_id = source.id if source else "unsourced"
            platform = safe_filename(source.platform if source else "unknown")
            source_indexes[source_id] = source_indexes.get(source_id, 0) + 1
            index = source_indexes[source_id]

            suffix = Path(item.filename).suffix or ".bin"
            archive_name = f"{platform}/{safe_filename(workspace)}/{safe_filename(source_id)}/{index:03d}{suffix}"
            archive.write(item.local_path, archive_name)

            source_meta = _source_metadata(source)
            manifest["media"].append({
                "id": item.id,
                "archive_path": archive_name,
                "filename": item.filename,
                "media_type": item.media_type,
                "mime_type": item.mime_type,
                "width": item.width,
                "height": item.height,
                "duration": item.duration,
                "file_size": item.file_size,
                **source_meta,
            })

            if source and source.id not in source_metadata_written:
                meta_path = f"{platform}/{safe_filename(workspace)}/{safe_filename(source.id)}/metadata.json"
                archive.writestr(meta_path, json.dumps(source_meta, indent=2, ensure_ascii=False))
                source_metadata_written.add(source.id)

        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    export.local_path = str(export_path)
    export.file_size = export_path.stat().st_size
    db.commit()
    db.refresh(export)
    return export
