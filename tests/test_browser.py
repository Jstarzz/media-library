from app.extractors.base import ExtractResult, MediaCandidate
from app.extractors.browser import score_network_candidate
from app.extractors.router import merge_results


def test_network_candidate_scoring_rejects_tiny_ui_assets():
    assert score_network_candidate("https://example.com/favicon.png", "image/png", 1200, "image") < 2
    assert score_network_candidate("https://cdn.example.com/photos/event-large.jpg", "image/jpeg", 250_000, "image") >= 2
    assert score_network_candidate("https://example.com/app.js", "application/javascript", 90_000, "script") < 0


def test_merge_results_deduplicates_media_and_fills_context():
    primary = ExtractResult(
        original_url="https://example.com",
        canonical_url="https://example.com",
        platform="web",
        extractor="generic-html",
        media=[MediaCandidate(url="https://example.com/a.jpg", media_type="image")],
    )
    rendered = ExtractResult(
        original_url="https://example.com",
        canonical_url="https://example.com",
        platform="web",
        extractor="playwright",
        title="Rendered title",
        media=[
            MediaCandidate(url="https://example.com/a.jpg", media_type="image"),
            MediaCandidate(url="https://example.com/b.jpg", media_type="image"),
        ],
    )

    result = merge_results(primary, rendered)
    assert result.title == "Rendered title"
    assert [item.url for item in result.media] == [
        "https://example.com/a.jpg",
        "https://example.com/b.jpg",
    ]
    assert result.extractor == "generic-html+playwright"
