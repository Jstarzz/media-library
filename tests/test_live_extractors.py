import json
import os

import pytest

from app.extractors.router import ExtractorRouter

pytestmark = pytest.mark.live


def _urls() -> list[str]:
    raw = os.getenv("MEDIA_LIBRARY_LIVE_URLS_JSON")
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(url, str) for url in value):
        raise ValueError("MEDIA_LIBRARY_LIVE_URLS_JSON must be a JSON array of URL strings")
    return value


@pytest.mark.asyncio
async def test_live_urls_extract_useful_content():
    urls = _urls()
    if not urls:
        pytest.skip("Set MEDIA_LIBRARY_LIVE_URLS_JSON to run live extraction checks")

    router = ExtractorRouter()
    failures = []
    for url in urls:
        try:
            result = await router.extract(url)
            if not (result.media or result.extracted_text or result.caption):
                failures.append(f"{url}: no useful content")
        except Exception as exc:
            failures.append(f"{url}: {exc}")

    assert not failures, "\n".join(failures)
