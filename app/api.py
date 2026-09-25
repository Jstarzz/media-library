from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db
from app.models import APIKey, Collection, IngestJob, IngestJobItem, MediaItem, Source, Workspace
from app.schemas import CollectionCreate, CollectionMediaAdd, JobCreate, KeyCreate, WorkspaceCreate
from app.security import Principal, assert_workspace, generate_api_key, hash_key, require_scope
from app.services.ingest import IngestService
from app.services.search import search_workspace

router = APIRouter(prefix="/api/v1")
ingest_service = IngestService()


def media_json(media: MediaItem) -> dict:
    base = get_settings().public_base_url.rstrip("/")
    return {
        "id": media.id, "type": media.media_type, "mime_type": media.mime_type,
        "width": media.width, "height": media.height, "duration": media.duration,
        "file_size": media.file_size,
        "thumbnail_url": f"{base}/api/v1/media/{media.id}/thumbnail" if media.thumbnail_path else None,
        "file_url": f"{base}/api/v1/media/{media.id}/file",
    }


def source_json(source: Source) -> dict:
    return {
        "id": source.id, "platform": source.platform, "title": source.title,
        "caption": source.caption, "author": source.author,
        "published_at": source.published_at.isoformat() if source.published_at else None,
        "source_url": source.original_url, "canonical_url": source.canonical_url,
        "extractor": source.extractor,
    }


@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    rows = db.scalars(select(Workspace).order_by(Workspace.name)).all()
    return [{"slug": row.slug, "name": row.name} for row in rows if principal.can_access(row.slug)]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db), _: Principal = Depends(require_scope("admin"))):
    if db.scalar(select(Workspace).where(Workspace.slug == body.slug)):
        raise HTTPException(409, "Workspace already exists")
    row = Workspace(slug=body.slug, name=body.name)
    db.add(row); db.commit()
    return {"slug": row.slug, "name": row.name}


@router.post("/keys", status_code=201)
def create_key(body: KeyCreate, db: Session = Depends(get_db), _: Principal = Depends(require_scope("admin"))):
    raw = generate_api_key()
    access = body.workspace_access if isinstance(body.workspace_access, str) else ",".join(body.workspace_access)
    key = APIKey(name=body.name, key_hash=hash_key(raw), workspace_access=access, scopes=",".join(body.scopes))
    db.add(key); db.commit()
    return {"id": key.id, "name": key.name, "key": raw, "workspace_access": access, "scopes": body.scopes}


@router.post("/jobs", status_code=202)
def create_job(body: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("ingest"))):
    assert_workspace(principal, body.workspace)
    if not db.scalar(select(Workspace).where(Workspace.slug == body.workspace)):
        raise HTTPException(404, "Workspace not found")
    urls = list(dict.fromkeys(url.strip() for url in body.urls if url.strip()))
    job = IngestJob(workspace_slug=body.workspace, name=body.name, auto_import=body.auto_import, total_urls=len(urls))
    db.add(job); db.flush()
    for url in urls:
        db.add(IngestJobItem(job_id=job.id, url=url))
    db.commit()
    background.add_task(ingest_service.run_job, job.id)
    return {"id": job.id, "status": job.status, "total_urls": job.total_urls}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    job = db.scalar(select(IngestJob).options(selectinload(IngestJob.items)).where(IngestJob.id == job_id))
    if not job: raise HTTPException(404, "Job not found")
    assert_workspace(principal, job.workspace_slug)
    return {
        "id": job.id, "workspace": job.workspace_slug, "status": job.status, "total_urls": job.total_urls,
        "scanned_urls": job.scanned_urls, "found_media": job.found_media, "imported_media": job.imported_media,
        "items": [{"id": i.id, "url": i.url, "status": i.status, "error": i.error} for i in job.items],
    }


@router.get("/workspaces/{workspace}/sources")
def list_sources(workspace: str, limit: int = Query(50, le=200), db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    assert_workspace(principal, workspace)
    rows = db.scalars(select(Source).where(Source.workspace_slug == workspace).order_by(Source.created_at.desc()).limit(limit)).all()
    return [source_json(row) for row in rows]


@router.get("/workspaces/{workspace}/media")
def list_media(workspace: str, media_type: str | None = None, limit: int = Query(50, le=200), offset: int = 0,
               db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    assert_workspace(principal, workspace)
    stmt = select(MediaItem).where(MediaItem.workspace_slug == workspace)
    if media_type: stmt = stmt.where(MediaItem.media_type == media_type)
    rows = db.scalars(stmt.order_by(MediaItem.created_at.desc()).offset(offset).limit(limit)).all()
    return [media_json(row) for row in rows]


@router.get("/workspaces/{workspace}/search")
def search(workspace: str, q: str = "", media_type: str | None = None, platform: str | None = None,
           author: str | None = None, limit: int = Query(20, le=100), db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    assert_workspace(principal, workspace)
    rows = search_workspace(db, workspace, q, media_type=media_type, platform=platform, author=author, limit=limit)
    return {"results": [{"source": source_json(row["source"]), "media": [media_json(m) for m in row["media"]]} for row in rows]}


@router.get("/workspaces/{workspace}/content")
def content(workspace: str, q: str = "", limit: int = Query(10, le=50), db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    assert_workspace(principal, workspace)
    rows = search_workspace(db, workspace, q, limit=limit)
    return {"items": [{"source_id": r["source"].id, "context": source_json(r["source"]), "text": r["source"].extracted_text or r["source"].caption or "", "media": [media_json(m) for m in r["media"]]} for r in rows]}


@router.get("/sources/{source_id}")
def get_source(source_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    source = db.scalar(select(Source).options(selectinload(Source.media)).where(Source.id == source_id))
    if not source: raise HTTPException(404, "Source not found")
    assert_workspace(principal, source.workspace_slug)
    return {**source_json(source), "description": source.description, "extracted_text": source.extracted_text, "media": [media_json(m) for m in source.media]}


@router.get("/media/{media_id}")
def get_media(media_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    media = db.get(MediaItem, media_id)
    if not media: raise HTTPException(404, "Media not found")
    assert_workspace(principal, media.workspace_slug)
    return media_json(media)


@router.get("/media/{media_id}/thumbnail")
def get_thumbnail(media_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    media = db.get(MediaItem, media_id)
    if not media or not media.thumbnail_path: raise HTTPException(404, "Thumbnail not found")
    assert_workspace(principal, media.workspace_slug)
    return FileResponse(media.thumbnail_path, media_type="image/webp")


@router.get("/media/{media_id}/file")
def get_file(media_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    media = db.get(MediaItem, media_id)
    if not media: raise HTTPException(404, "Media not found")
    assert_workspace(principal, media.workspace_slug)
    return FileResponse(media.local_path, media_type=media.mime_type, filename=media.filename)


@router.get("/collections")
def list_collections(workspace: str | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("read"))):
    stmt = select(Collection)
    if workspace:
        assert_workspace(principal, workspace); stmt = stmt.where(Collection.workspace_slug == workspace)
    rows = db.scalars(stmt.order_by(Collection.name)).all()
    return [{"id": row.id, "workspace": row.workspace_slug, "name": row.name, "description": row.description, "media_count": len(row.media)} for row in rows if principal.can_access(row.workspace_slug)]


@router.post("/collections", status_code=201)
def create_collection(body: CollectionCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("admin"))):
    assert_workspace(principal, body.workspace)
    row = Collection(workspace_slug=body.workspace, name=body.name, description=body.description)
    db.add(row); db.commit()
    return {"id": row.id, "workspace": row.workspace_slug, "name": row.name}


@router.post("/collections/{collection_id}/media")
def add_collection_media(collection_id: str, body: CollectionMediaAdd, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("admin"))):
    collection = db.get(Collection, collection_id)
    if not collection: raise HTTPException(404, "Collection not found")
    assert_workspace(principal, collection.workspace_slug)
    rows = db.scalars(select(MediaItem).where(MediaItem.id.in_(body.media_ids), MediaItem.workspace_slug == collection.workspace_slug)).all()
    for row in rows:
        if row not in collection.media: collection.media.append(row)
    db.commit()
    return {"id": collection.id, "media_count": len(collection.media)}
