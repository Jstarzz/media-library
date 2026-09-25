import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Collection, ExportJob, IngestJob, IngestJobItem, MediaItem, Source, Workspace
from app.services.exports import create_export
from app.services.ingest import IngestService
from app.services.search import search_workspace

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
ingest_service = IngestService()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    workspaces = db.scalars(select(Workspace).order_by(Workspace.name)).all()
    return templates.TemplateResponse(request, "index.html", {"workspaces": workspaces})


@router.post("/workspaces")
def create_workspace(slug: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    slug = slug.strip().lower()
    if db.scalar(select(Workspace).where(Workspace.slug == slug)):
        return RedirectResponse(f"/workspaces/{slug}", 303)
    db.add(Workspace(slug=slug, name=name.strip())); db.commit()
    return RedirectResponse(f"/workspaces/{slug}", 303)


@router.get("/workspaces/{workspace}", response_class=HTMLResponse)
def workspace_library(
    request: Request,
    workspace: str,
    q: str = "",
    media_type: str | None = None,
    platform: str | None = None,
    collection: str | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    ws = db.scalar(select(Workspace).where(Workspace.slug == workspace))
    if not ws: raise HTTPException(404, "Workspace not found")

    page_size = 48
    if q:
        grouped = search_workspace(db, workspace, q, media_type=media_type, platform=platform, limit=150)
        media = [m for result in grouped for m in result["media"]]
        if collection:
            media = [m for m in media if any(c.id == collection for c in m.collections)]
        has_next = False
    else:
        stmt = select(MediaItem).where(MediaItem.workspace_slug == workspace)
        if media_type:
            stmt = stmt.where(MediaItem.media_type == media_type)
        if platform:
            stmt = stmt.where(MediaItem.sources.any(Source.platform == platform))
        if collection:
            stmt = stmt.where(MediaItem.collections.any(Collection.id == collection))
        rows = list(db.scalars(stmt.order_by(MediaItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size + 1)))
        has_next = len(rows) > page_size
        media = rows[:page_size]

    source_count = db.scalar(select(func.count()).select_from(Source).where(Source.workspace_slug == workspace)) or 0
    media_count = db.scalar(select(func.count()).select_from(MediaItem).where(MediaItem.workspace_slug == workspace)) or 0
    collections = db.scalars(select(Collection).where(Collection.workspace_slug == workspace).order_by(Collection.name)).all()
    platforms = [row[0] for row in db.execute(select(Source.platform).where(Source.workspace_slug == workspace).distinct().order_by(Source.platform)).all()]
    return templates.TemplateResponse(request, "workspace.html", {
        "workspace": ws, "media": media, "q": q, "media_type": media_type or "", "platform": platform or "",
        "collection_id": collection or "", "page": page, "has_next": has_next, "source_count": source_count,
        "media_count": media_count, "collections": collections, "platforms": platforms,
    })


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_db)):
    workspaces = db.scalars(select(Workspace).order_by(Workspace.name)).all()
    return templates.TemplateResponse(request, "import.html", {"workspaces": workspaces})


@router.post("/import")
def import_submit(background: BackgroundTasks, workspace: str = Form(...), urls: str = Form(...), mode: str = Form("auto"), db: Session = Depends(get_db)):
    values = list(dict.fromkeys(line.strip() for line in urls.splitlines() if line.strip()))
    job = IngestJob(workspace_slug=workspace, total_urls=len(values), auto_import=False)
    db.add(job); db.flush()
    for url in values: db.add(IngestJobItem(job_id=job.id, url=url))
    db.commit()
    background.add_task(ingest_service.run_job, job.id, mode == "generic")
    return RedirectResponse(f"/jobs/{job.id}", 303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    job = db.scalar(select(IngestJob).options(selectinload(IngestJob.items)).where(IngestJob.id == job_id))
    if not job: raise HTTPException(404, "Job not found")
    scans = {}
    total_candidates = 0
    for item in job.items:
        if item.scan_json:
            scan = json.loads(item.scan_json)
            scans[item.id] = scan
            total_candidates += len(scan.get("media", []))
    return templates.TemplateResponse(request, "job.html", {"job": job, "scans": scans, "total_candidates": total_candidates})


@router.post("/jobs/{job_id}/import")
def job_import(
    job_id: str,
    background: BackgroundTasks,
    mode: str = Form("selected"),
    selected: list[str] | None = Form(None),
):
    selected_map = None
    if mode != "all":
        selected_map = {}
        for value in selected or []:
            item_id, sep, index = value.rpartition(":")
            if sep and index.isdigit():
                selected_map.setdefault(item_id, []).append(int(index))
        if not selected_map:
            return RedirectResponse(f"/jobs/{job_id}", 303)
    background.add_task(ingest_service.import_job, job_id, selected_map)
    return RedirectResponse(f"/jobs/{job_id}", 303)


@router.get("/collections", response_class=HTMLResponse)
def collections_page(request: Request, workspace: str | None = None, db: Session = Depends(get_db)):
    workspaces = db.scalars(select(Workspace).order_by(Workspace.name)).all()
    stmt = select(Collection).options(selectinload(Collection.media)).order_by(Collection.workspace_slug, Collection.name)
    if workspace:
        stmt = stmt.where(Collection.workspace_slug == workspace)
    collections = db.scalars(stmt).all()
    return templates.TemplateResponse(request, "collections.html", {"workspaces": workspaces, "collections": collections, "selected_workspace": workspace or ""})


@router.post("/collections")
def create_collection_ui(workspace: str = Form(...), name: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    row = Collection(workspace_slug=workspace, name=name.strip(), description=description.strip() or None)
    db.add(row); db.commit()
    return RedirectResponse(f"/collections/{row.id}", 303)


@router.get("/collections/{collection_id}", response_class=HTMLResponse)
def collection_page(request: Request, collection_id: str, db: Session = Depends(get_db)):
    collection = db.scalar(select(Collection).options(selectinload(Collection.media)).where(Collection.id == collection_id))
    if not collection: raise HTTPException(404, "Collection not found")
    return templates.TemplateResponse(request, "collection.html", {"collection": collection})


@router.post("/collections/{collection_id}/remove")
def collection_remove(collection_id: str, media_ids: list[str] | None = Form(None), db: Session = Depends(get_db)):
    collection = db.scalar(select(Collection).options(selectinload(Collection.media)).where(Collection.id == collection_id))
    if not collection: raise HTTPException(404, "Collection not found")
    remove = set(media_ids or [])
    collection.media[:] = [item for item in collection.media if item.id not in remove]
    db.commit()
    return RedirectResponse(f"/collections/{collection_id}", 303)


@router.post("/workspaces/{workspace}/collections/add")
def add_to_collection(workspace: str, collection_id: str = Form(...), media_ids: list[str] | None = Form(None), db: Session = Depends(get_db)):
    collection = db.scalar(select(Collection).options(selectinload(Collection.media)).where(Collection.id == collection_id, Collection.workspace_slug == workspace))
    if not collection: raise HTTPException(404, "Collection not found")
    ids = media_ids or []
    rows = db.scalars(select(MediaItem).where(MediaItem.workspace_slug == workspace, MediaItem.id.in_(ids))).all()
    existing = {item.id for item in collection.media}
    collection.media.extend(item for item in rows if item.id not in existing)
    db.commit()
    return RedirectResponse(f"/workspaces/{workspace}?collection={collection.id}", 303)


@router.post("/workspaces/{workspace}/export")
def export_selected(workspace: str, media_ids: list[str] | None = Form(None), collection_id: str | None = Form(None), db: Session = Depends(get_db)):
    try:
        export = create_export(db, workspace, media_ids=media_ids or None, collection_id=collection_id or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/exports/{export.id}/file", 303)


@router.post("/workspaces/{workspace}/media/delete")
def delete_media(workspace: str, media_ids: list[str] | None = Form(None), db: Session = Depends(get_db)):
    ids = media_ids or []
    rows = db.scalars(select(MediaItem).where(MediaItem.workspace_slug == workspace, MediaItem.id.in_(ids))).all()
    for item in rows:
        Path(item.local_path).unlink(missing_ok=True)
        if item.thumbnail_path:
            Path(item.thumbnail_path).unlink(missing_ok=True)
        db.delete(item)
    db.commit()
    return RedirectResponse(f"/workspaces/{workspace}", 303)


@router.get("/exports/{export_id}/file")
def export_file_ui(export_id: str, db: Session = Depends(get_db)):
    export = db.get(ExportJob, export_id)
    if not export: raise HTTPException(404, "Export not found")
    return FileResponse(export.local_path, media_type="application/zip", filename=f"{export.workspace_slug}-{export.id}.zip")


@router.get("/media/{media_id}", response_class=HTMLResponse)
def media_page(request: Request, media_id: str, db: Session = Depends(get_db)):
    media = db.scalar(select(MediaItem).options(selectinload(MediaItem.sources), selectinload(MediaItem.collections)).where(MediaItem.id == media_id))
    if not media: raise HTTPException(404, "Media not found")
    collections = db.scalars(select(Collection).where(Collection.workspace_slug == media.workspace_slug).order_by(Collection.name)).all()
    return templates.TemplateResponse(request, "media.html", {"media": media, "source": media.sources[0] if media.sources else None, "collections": collections})


@router.get("/media/{media_id}/file")
def ui_media_file(media_id: str, db: Session = Depends(get_db)):
    media = db.get(MediaItem, media_id)
    if not media: raise HTTPException(404, "Media not found")
    return FileResponse(media.local_path, media_type=media.mime_type, filename=media.filename)


@router.get("/media/{media_id}/thumbnail")
def ui_media_thumbnail(media_id: str, db: Session = Depends(get_db)):
    media = db.get(MediaItem, media_id)
    if not media or not media.thumbnail_path: raise HTTPException(404, "Thumbnail not found")
    return FileResponse(media.thumbnail_path, media_type="image/webp")
