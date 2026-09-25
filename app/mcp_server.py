from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory, init_db
from app.models import Collection, MediaItem, Source, Workspace
from app.security import Principal, assert_workspace, principal_for_token
from app.services.search import search_workspace

mcp = FastMCP("media-library")


def _base() -> str:
    return get_settings().public_base_url.rstrip("/")


def _principal(db) -> Principal:
    token = get_settings().mcp_api_key
    if not token:
        raise RuntimeError("MEDIA_LIBRARY_MCP_API_KEY is required for MCP access")
    return principal_for_token(token, db)


@mcp.tool()
def list_workspaces() -> list[dict]:
    """List Media Library workspaces visible to this MCP API key."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db)
        return [{"slug": row.slug, "name": row.name} for row in db.scalars(select(Workspace).order_by(Workspace.name)) if principal.can_access(row.slug)]


@mcp.tool()
def search_media(workspace: str, query: str, media_type: str | None = None, limit: int = 20) -> list[dict]:
    """Search client media with source context."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db); assert_workspace(principal, workspace)
        rows = search_workspace(db, workspace, query, media_type=media_type, limit=min(limit, 50))
        output = []
        for row in rows:
            source = row["source"]
            for media in row["media"]:
                output.append({
                    "media_id": media.id, "type": media.media_type, "width": media.width, "height": media.height,
                    "thumbnail_url": f"{_base()}/api/v1/media/{media.id}/thumbnail" if media.thumbnail_path else None,
                    "file_url": f"{_base()}/api/v1/media/{media.id}/file",
                    "caption": source.caption, "date": source.published_at.isoformat() if source.published_at else None,
                    "source_url": source.original_url, "platform": source.platform,
                })
        return output[:limit]


@mcp.tool()
def search_content(workspace: str, query: str, limit: int = 10) -> list[dict]:
    """Search normalized client source/content bundles."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db); assert_workspace(principal, workspace)
        rows = search_workspace(db, workspace, query, limit=min(limit, 50))
        return [{
            "source_id": row["source"].id, "title": row["source"].title, "caption": row["source"].caption,
            "text": row["source"].extracted_text, "author": row["source"].author,
            "source_url": row["source"].original_url, "media_ids": [m.id for m in row["media"]],
        } for row in rows]


@mcp.tool()
def get_source(source_id: str) -> dict:
    """Get one source and its media IDs."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db)
        source = db.get(Source, source_id)
        if not source: return {"error": "not found"}
        assert_workspace(principal, source.workspace_slug)
        return {"id": source.id, "platform": source.platform, "title": source.title, "caption": source.caption, "author": source.author, "source_url": source.original_url, "text": source.extracted_text, "media_ids": [m.id for m in source.media]}


@mcp.tool()
def get_media(media_id: str) -> dict:
    """Get media metadata and retrievable URLs."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db)
        media = db.get(MediaItem, media_id)
        if not media: return {"error": "not found"}
        assert_workspace(principal, media.workspace_slug)
        return {"id": media.id, "type": media.media_type, "mime_type": media.mime_type, "width": media.width, "height": media.height, "file_size": media.file_size, "thumbnail_url": f"{_base()}/api/v1/media/{media.id}/thumbnail" if media.thumbnail_path else None, "file_url": f"{_base()}/api/v1/media/{media.id}/file"}


@mcp.tool()
def get_media_file(media_id: str) -> dict:
    """Return the authenticated REST URL for an original media file."""
    data = get_media(media_id)
    if "error" in data:
        return data
    return {"media_id": media_id, "file_url": data["file_url"]}


@mcp.tool()
def list_collections(workspace: str) -> list[dict]:
    """List collections in one workspace."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db); assert_workspace(principal, workspace)
        rows = db.scalars(select(Collection).where(Collection.workspace_slug == workspace).order_by(Collection.name)).all()
        return [{"id": row.id, "name": row.name, "media_count": len(row.media)} for row in rows]


@mcp.tool()
def get_collection(collection_id: str) -> dict:
    """Get a collection and its media IDs."""
    init_db()
    with get_session_factory()() as db:
        principal = _principal(db)
        row = db.get(Collection, collection_id)
        if not row: return {"error": "not found"}
        assert_workspace(principal, row.workspace_slug)
        return {"id": row.id, "workspace": row.workspace_slug, "name": row.name, "description": row.description, "media_ids": [m.id for m in row.media]}


if __name__ == "__main__":
    init_db()
    mcp.run()
