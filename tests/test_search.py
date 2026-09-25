from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Source, Workspace
from app.services.search import index_source, search_workspace


def test_fts_workspace_isolation():
    with Session(get_engine()) as db:
        db.add_all([Workspace(slug="dte", name="DTE"), Workspace(slug="ziz", name="ZIZ")]); db.flush()
        a = Source(workspace_slug="dte", original_url="https://example.com/1", canonical_url="https://example.com/1", platform="web", caption="Carnival highlights")
        b = Source(workspace_slug="ziz", original_url="https://example.com/2", canonical_url="https://example.com/2", platform="web", caption="Carnival newsroom")
        db.add_all([a,b]); db.flush(); index_source(db,a); index_source(db,b); db.commit()
        rows = search_workspace(db, "dte", "carnival")
        assert [r["source"].workspace_slug for r in rows] == ["dte"]
