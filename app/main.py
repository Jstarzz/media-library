from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from app.api import router as api_router
from app.database import get_session_factory, init_db
from app.models import IngestJob
from app.ui import router as ui_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with get_session_factory()() as db:
        db.execute(update(IngestJob).where(IngestJob.status.in_(["scanning", "importing"])).values(status="interrupted"))
        db.commit()
    yield


app = FastAPI(title="Media Library", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router)
app.include_router(ui_router)


@app.get("/health")
def health():
    return {"status": "ok"}
