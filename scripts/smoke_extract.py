#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys

from app.extractors.router import ExtractorRouter


async def main(urls: list[str], require_media: bool) -> int:
    router = ExtractorRouter()
    failures = 0

    for url in urls:
        try:
            result = await router.extract(url)
            payload = {
                "url": url,
                "platform": result.platform,
                "extractor": result.extractor,
                "title": result.title,
                "media_count": len(result.media),
                "warnings": result.warnings,
            }
            print(json.dumps(payload, ensure_ascii=False))
            if require_media and not result.media:
                failures += 1
                print(f"ERROR {url}: no media discovered", file=sys.stderr)
        except Exception as exc:
            failures += 1
            print(f"ERROR {url}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise Media Library extractors against real URLs")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--require-media", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.urls, args.require_media)))
