from collections import defaultdict

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models import ContentRecord, MediaItem, Source


def _fts_query(query: str) -> str:
    terms = [term.replace('"', "") for term in query.split() if term.strip()]
    return " AND ".join(f'"{term}"*' for term in terms)


def index_source(db: Session, source: Source) -> None:
    db.execute(text("DELETE FROM search_index WHERE source_id = :source_id"), {"source_id": source.id})
    chunks = [source.title, source.caption, source.description, source.author, source.extracted_text]
    body = "\n".join(value for value in chunks if value)
    if body:
        db.execute(text("INSERT INTO search_index(workspace_slug, source_id, media_id, kind, text) VALUES (:ws,:src,NULL,'source',:body)"),
                   {"ws": source.workspace_slug, "src": source.id, "body": body})
    for record in db.scalars(select(ContentRecord).where(ContentRecord.source_id == source.id)):
        db.execute(text("INSERT INTO search_index(workspace_slug, source_id, media_id, kind, text) VALUES (:ws,:src,:med,:kind,:body)"),
                   {"ws": source.workspace_slug, "src": source.id, "med": record.media_id, "kind": record.content_type, "body": record.text})


def search_workspace(db: Session, workspace: str, query: str, *, media_type: str | None = None,
                     platform: str | None = None, author: str | None = None, limit: int = 20) -> list[dict]:
    params = {"ws": workspace, "q": _fts_query(query), "limit": min(limit, 100)}
    rows = db.execute(text("""
        SELECT source_id, media_id, kind, bm25(search_index) AS rank
        FROM search_index
        WHERE workspace_slug = :ws AND search_index MATCH :q
        ORDER BY rank
        LIMIT :limit
    """), params).mappings().all() if query.strip() else []

    source_ids = []
    for row in rows:
        if row["source_id"] and row["source_id"] not in source_ids:
            source_ids.append(row["source_id"])

    if not query.strip():
        stmt = select(Source.id).where(Source.workspace_slug == workspace).order_by(Source.published_at.desc(), Source.created_at.desc()).limit(min(limit, 100))
        source_ids = list(db.scalars(stmt))

    results = []
    for source_id in source_ids:
        source = db.get(Source, source_id)
        if not source or source.workspace_slug != workspace:
            continue
        if platform and source.platform != platform:
            continue
        if author and (source.author or "").lower() != author.lower():
            continue
        media = [m for m in source.media if not media_type or m.media_type == media_type]
        if media_type and not media:
            continue
        results.append({"source": source, "media": media})
        if len(results) >= limit:
            break
    return results
