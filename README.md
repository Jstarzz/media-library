# Media Library

Reusable internal media/content layer for client projects. Humans can scan links, preview discovered media, selectively import it into permanent client workspaces, browse/search it later, organize it into collections, and export clean ZIP bundles. Coding/content agents get the same normalized content through REST and MCP.

## v0.1 feature set

- FastAPI + SQLite + FTS5
- Jinja2 + HTMX/Alpine server-rendered UI
- workspace/client isolation
- persisted scan/import jobs
- Facebook / Instagram adapters through `gallery-dl`
- YouTube / TikTok / video extraction through `yt-dlp`
- generic static HTML/metadata/JSON-LD discovery
- Playwright Chromium rendered-DOM + media-network fallback
- per-candidate scan review and selective import
- permanent local media storage + SHA-256 dedupe
- image/video thumbnails with Pillow/ffmpeg
- responsive library grid, search and platform/media/collection filters
- bulk add-to-collection, delete and ZIP export
- collection browser/detail UI
- ZIP exports with `manifest.json` and per-source `metadata.json`
- REST API with scoped, hashed API keys
- MCP tools for workspace/content/media/collection discovery
- SSRF protection for HTTP fetches and browser requests
- Docker Compose deployment
- unit CI + Docker build CI
- opt-in live extractor smoke workflow

The extractor layer is adapter-based. Services, UI, REST and MCP consume only normalized `ExtractResult` / `MediaCandidate` data.

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

## Human workflow

1. Create/select a client workspace.
2. Open **Import** and paste one URL per line.
3. Scan. Known social platforms use their dedicated adapters first; generic pages fall back to rendered Chromium when static discovery is thin.
4. Review the candidates. Everything starts selected; uncheck junk and press **Import selected**, or import everything.
5. Browse the client library, search/filter it, bulk-add items to collections, export selected media, or delete imported files.
6. Open **Collections** for reusable media sets such as “Carnival 2026”, “Website Hero Candidates”, or “Staff”.

## First workspace through REST

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"slug":"dte","name":"DTE"}'
```

## Scan / import through REST

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

Poll `GET /api/v1/jobs/{id}`. For human review, leave `auto_import` false and use the web job page.

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

## Export

Export selected media:

```bash
curl -X POST http://localhost:8000/api/v1/exports \
  -H "Authorization: Bearer $MEDIA_LIBRARY_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"dte","media_ids":["med_a","med_b"]}'
```

Or export a whole collection:

```json
{"workspace":"dte","collection_id":"col_xxx"}
```

The ZIP layout is:

```text
manifest.json
facebook/
  dte/
    src_.../
      001.jpg
      002.jpg
      metadata.json
instagram/
  dte/
    src_.../
      001.jpg
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

They are consumed only by the relevant extraction tools. Keep them out of git and only ingest public content or content you are authorized to access.

## Generic rendered discovery

The generic extractor first parses static HTML. If it finds fewer than two media candidates, the router launches headless Chromium, scrolls the page a few times to trigger lazy loading, reparses the rendered DOM, and observes media network responses.

Browser requests are checked against the same public-network policy as direct HTTP fetches. Localhost, RFC1918, link-local, metadata and other non-public destinations are aborted.

Tune with:

```text
MEDIA_LIBRARY_BROWSER_ENABLED=true
MEDIA_LIBRARY_BROWSER_TIMEOUT_MS=20000
MEDIA_LIBRARY_BROWSER_SCROLLS=3
```

## MCP

Run the MCP server using a normal Media Library API key:

```bash
export MEDIA_LIBRARY_MCP_API_KEY=ml_xxxxxxxxx
python -m app.mcp_server
```

Tools:

- `list_workspaces`
- `search_content`
- `search_media`
- `get_source`
- `get_media`
- `get_media_file`
- `list_collections`
- `get_collection`

Set `MEDIA_LIBRARY_PUBLIC_BASE_URL` to the externally reachable Media Library base URL so agent-returned media URLs are usable.

## Add an extractor

1. Implement `supports(url)` and async `extract(url) -> ExtractResult` under `app/extractors/`.
2. Normalize output into `ExtractResult` + `MediaCandidate`.
3. Register adapter order in `app/extractors/router.py`.
4. Fail locally and let the router fall through; one broken extractor/URL must not kill a batch.
5. Add a focused routing/normalization test.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m playwright install chromium
pytest -q -m 'not live'
uvicorn app.main:app --reload
```

## Live extractor checks

Social sites change constantly, so real-network checks are opt-in instead of poisoning deterministic CI.

Locally:

```bash
MEDIA_LIBRARY_LIVE_URLS_JSON='[
  "https://www.youtube.com/watch?v=...",
  "https://www.tiktok.com/@.../video/...",
  "https://www.instagram.com/p/...",
  "https://www.facebook.com/..."
]' pytest -q -m live
```

Or directly:

```bash
python scripts/smoke_extract.py --require-media \
  'https://www.youtube.com/watch?v=...' \
  'https://www.instagram.com/p/...'
```

GitHub also has a manually dispatched **Live extraction smoke** workflow that accepts a JSON array of public/authorized URLs.

## Notes

- Imported originals are permanent until explicitly deleted.
- Scans are discovery; importing is the point where originals are persisted.
- Generic rendered discovery does not recursively crawl websites.
- API/MCP callers never need filesystem paths.
- The SQLite database owns relationships; the folder layout is storage, not the database.
