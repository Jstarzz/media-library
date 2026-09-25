import json

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import IngestJob, IngestJobItem, MediaItem, Source, Workspace
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
def workspace_library(request: Request, workspace: str, q: str = "", media_type: str | None = None,
                      platform: str | None = None, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    ws = db.scalar(select(Workspace).where(Workspace.slug == workspace))
    if not ws: raise HTTPException(404, "Workspace not found")
    page_size = 48
    if q:
        grouped = search_workspace(db, workspace, q, media_type=media_type, platform=platform, limit=100)
        media = [m for result in grouped for m in result["media"]]
    else:
        stmt = select(MediaItem).where(MediaItem.workspace_slug == workspace)
        if media_type: stmt = stmt.where(MediaItem.media_type == media_type)
        media = db.scalars(stmt.order_by(MediaItem.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    source_count = db.scalar(select(func.count()).select_from(Source).where(Source.workspace_slug == workspace)) or 0
    media_count = db.scalar(select(func.count()).select_from(MediaItem).where(MediaItem.workspace_slug == workspace)) or 0
    return templates.TemplateResponse(request, "workspace.html", {"workspace": ws, "media": media, "q": q, "media_type": media_type or "", "platform": platform or "", "page": page, "source_count": source_count, "media_count": media_count})


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
    for item in job.items:
        if item.scan_json:
            scans[item.id] = json.loads(item.scan_json)
    return templates.TemplateResponse(request, "job.html", {"job": job, "scans": scans})


@router.post("/jobs/{job_id}/import")
def job_import(job_id: str, background: BackgroundTasks):
    background.add_task(ingest_service.import_job, job_id)
    return RedirectResponse(f"/jobs/{job_id}", 303)


@router.get("/media/{media_id}", response_class=HTMLResponse)
def media_page(request: Request, media_id: str, db: Session = Depends(get_db)):
    media = db.scalar(select(MediaItem).options(selectinload(MediaItem.sources)).where(MediaItem.id == media_id))
    if not media: raise HTTPException(404, "Media not found")
    return templates.TemplateResponse(request, "media.html", {"media": media, "source": media.sources[0] if media.sources else None})


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
