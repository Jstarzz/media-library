# Media Library

Reusable internal media/content layer for client projects. Humans can scan links, preview discovered media, import it into permanent client workspaces, browse/search it later, and retrieve originals. Coding/content agents get the same content through REST and MCP.

## What works in v0.1

- FastAPI + SQLite + FTS5
- Jinja/HTMX-friendly server-rendered library UI
- workspace/client isolation
- persisted scan/import jobs
- generic webpage extraction (metadata, DOM media, JSON-LD, article text)
- social extraction adapters using `gallery-dl` and `yt-dlp` with graceful fallback
- permanent local media storage + SHA-256 dedupe
- image/video thumbnails (Pillow/ffmpeg)
- lexical full-text search
- REST API with scoped, hashed API keys
- MCP tools for workspace/content/media discovery
- collections model/API
- SSRF checks on fetched URLs and redirects
- Docker Compose deployment

The extractor layer is intentionally adapter-based; the rest of the app does not consume raw `yt-dlp` or `gallery-dl` data structures.

## Run

```bash
cp .env.example .env
# Set a real MEDIA_LIBRARY_ADMIN_TOKEN in .env
docker compose up -d --build
```

Open `http://localhost:8000`.

Health check:

```bash
curl http://localhost:8000/health
```

## First workspace

Create one in the UI, or:

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"slug":"dte","name":"DTE"}'
```

## Scan / import from REST

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace":"dte",
    "urls":["https://example.com/news/event"],
    "auto_import":true
  }'
```

Poll `GET /api/v1/jobs/{id}`. For human review, leave `auto_import` false and use the web job page to inspect scan results before importing.

## Search / retrieve

```bash
curl 'http://localhost:8000/api/v1/workspaces/dte/search?q=carnival&media_type=image&limit=20' \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN"
```

Media metadata:

```bash
curl http://localhost:8000/api/v1/media/med_xxx \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN"
```

Original bytes:

```bash
curl -L http://localhost:8000/api/v1/media/med_xxx/file \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" -o asset.bin
```

## Issue a restricted agent key

Only the raw key returned at creation time is shown; the database stores its SHA-256 hash.

```bash
curl -X POST http://localhost:8000/api/v1/keys \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"dte-agent","workspace_access":["dte"],"scopes":["read"]}'
```

Trusted ingest agents can receive `read` + `ingest`.

## Social cookies

Optional Netscape-format cookies:

```text
/data/auth/facebook.cookies.txt
/data/auth/instagram.cookies.txt
/data/auth/tiktok.cookies.txt
/data/auth/youtube.cookies.txt
```

They are never exposed by the API. Keep them out of git. Only ingest public content or content you are authorized to access.

## MCP

The MCP server imports the same database/search service layer as REST.

Run it alongside the app using a normal Media Library API key:

```bash
export MEDIA_LIBRARY_MCP_API_KEY=ml_xxxxxxxxx
python -m app.mcp_server
```

It exposes tools:

- `list_workspaces`
- `search_content`
- `search_media`
- `get_source`
- `get_media`
- `list_collections`
- `get_collection`
- `get_media_file`

For remote agents, set `MEDIA_LIBRARY_PUBLIC_BASE_URL` to the externally reachable Media Library base URL so returned `thumbnail_url` / `file_url` values are usable.

## Add an extractor

1. Implement `supports(url)` and async `extract(url) -> ExtractResult` under `app/extractors/`.
2. Normalize output into `ExtractResult` + `MediaCandidate`. Do not leak tool-specific payloads into services/UI/API.
3. Register the adapter order in `app/extractors/router.py`.
4. Fail locally and let the router fall through; one extractor or URL must not kill a batch.
5. Add a focused test for platform routing/normalization.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
uvicorn app.main:app --reload
```

## Known v0.1 limits

- Browser-rendered Playwright discovery is not wired yet; generic extraction currently covers static HTML/JSON-LD plus known-platform tools.
- Scan review currently supports “import everything”; per-candidate checkbox import is the next UI pass.
- Export ZIP generation and richer collection UI are not yet exposed in the web UI.
- MCP transport is intentionally thin; deploy it behind your normal network/auth boundary and use REST bearer auth for direct HTTP agents.

Those are explicit next slices, not reasons to block the basic library workflow.
