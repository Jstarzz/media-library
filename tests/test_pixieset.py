from app.extractors.base import ExtractResult, MediaCandidate
from app.extractors.pixieset import (
    is_pixieset_host,
    looks_like_pixieset,
    parse_gallery_page,
    photo_to_candidate,
)
from app.extractors.router import ExtractorRouter


GALLERY_HTML = """
<html><head><title>Summer Crush by Jay Black Productions</title></head><body>
<script>
  window.config = {'collectionId':48587248,'collectionUrlKey':'summer\\x2Dcrush',
    'sets':[{'id':1,'slug':'finals'},{'id':2,'slug':'proofs'},{'id':3,'slug':'finals'}]};
</script></body></html>
"""


def test_detects_pixieset_hosts_only():
    assert is_pixieset_host("https://jayblackphotos.pixieset.com/summercrush/")
    assert is_pixieset_host("https://pixieset.com/")
    assert not is_pixieset_host("https://gallery.refiic.com/djtero-sunset/")
    assert not is_pixieset_host("https://notpixieset.com/x")


def test_custom_domain_is_recognised_by_its_image_cdn():
    result = ExtractResult(
        original_url="https://gallery.refiic.com/x/",
        canonical_url=None,
        platform="web",
        extractor="generic-html",
        media=[MediaCandidate(url="https://images.pixieset.com/1/abc-cover.jpg", media_type="image")],
    )
    assert looks_like_pixieset(result)
    result.media = [MediaCandidate(url="https://example.com/a.jpg", media_type="image")]
    assert not looks_like_pixieset(result)
    assert not looks_like_pixieset(None)


def test_parses_collection_config_and_dedupes_sets():
    meta = parse_gallery_page(GALLERY_HTML)
    assert meta["cid"] == "48587248"
    assert meta["cuk"] == "summer-crush"
    assert meta["sets"] == ["finals", "proofs"]
    assert meta["title"] == "Summer Crush by Jay Black Productions"


def test_non_gallery_page_has_no_collection():
    meta = parse_gallery_page("<html><title>Login</title></html>")
    assert meta["cid"] is None and meta["cuk"] is None
    assert meta["sets"] == ["highlights"]


def test_photo_uses_largest_size_and_scales_dimensions_to_the_cap():
    photo = {
        "id": 10816934095,
        "name": "IMG_0200.jpg",
        "width": 3840,
        "height": 2560,
        "maxWidth": 1600,
        "maxHeight": 1600,
        "pathThumb": "//images.pixieset.com/1/a-thumb.jpg",
        "pathLarge": "//images.pixieset.com/1/a-large.jpg",
        "pathXxlarge": "//images.pixieset.com/1/a-xxlarge.jpg",
    }
    candidate = photo_to_candidate(photo, "finals")
    assert candidate.url == "https://images.pixieset.com/1/a-xxlarge.jpg"
    assert (candidate.width, candidate.height) == (1600, 1067)
    assert candidate.platform_media_id == "10816934095"
    assert candidate.filename == "IMG_0200.jpg"
    assert candidate.thumbnail_url == "https://images.pixieset.com/1/a-thumb.jpg"


def test_photo_without_any_size_is_skipped():
    assert photo_to_candidate({"id": 1, "name": "x.jpg"}, "finals") is None


async def test_router_sends_pixieset_hosts_to_the_pixieset_extractor(monkeypatch):
    router = ExtractorRouter()
    called = {}

    async def fake_extract(url):
        called["url"] = url
        return ExtractResult(
            original_url=url,
            canonical_url=url,
            platform="pixieset",
            extractor="pixieset",
            media=[MediaCandidate(url="https://images.pixieset.com/1/a-xxlarge.jpg", media_type="image")],
        )

    monkeypatch.setattr(router.pixieset, "extract", fake_extract)
    result = await router.extract("https://jayblackphotos.pixieset.com/summercrush/")
    assert called["url"] == "https://jayblackphotos.pixieset.com/summercrush/"
    assert result.extractor == "pixieset"
