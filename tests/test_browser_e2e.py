import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app.extractors.browser as browser_module
from app.extractors.browser import BrowserExtractor


class DynamicMediaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/dynamic.jpg":
            body = b"x" * 30_000
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"""<!doctype html>
        <html><head><title>Rendered event</title></head>
        <body>
          <main><h1>Dynamic gallery</h1></main>
          <script>
            setTimeout(() => {
              const img = document.createElement('img');
              img.src = '/dynamic.jpg';
              img.alt = 'Loaded after JavaScript';
              document.querySelector('main').appendChild(img);
            }, 50);
          </script>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.mark.asyncio
async def test_playwright_discovers_js_injected_media(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), DynamicMediaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    monkeypatch.setattr(browser_module, "validate_public_url", lambda url: url)
    url = f"http://127.0.0.1:{server.server_port}/"

    try:
        result = await BrowserExtractor().extract(url)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert result.extractor == "playwright"
    assert result.title == "Rendered event"
    assert any(item.url.endswith("/dynamic.jpg") for item in result.media)
