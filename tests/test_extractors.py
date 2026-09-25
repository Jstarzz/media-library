from app.extractors.generic import extract_html
from app.extractors.tools import detect_platform


def test_platform_detection():
    assert detect_platform("https://www.facebook.com/x") == "facebook"
    assert detect_platform("https://youtu.be/abc") == "youtube"
    assert detect_platform("https://example.com/x") == "web"


def test_generic_html_discovers_media_and_text():
    result = extract_html("https://example.com/news", """
      <html><head><title>Event</title><meta property='og:image' content='/hero.jpg'></head>
      <body><article><h1>Graduation</h1><p>Community ceremony</p><img srcset='/small.jpg 320w, /big.jpg 1600w'></article></body></html>
    """)
    assert result.title == "Event"
    assert "Graduation" in result.extracted_text
    assert [m.url for m in result.media] == ["https://example.com/hero.jpg", "https://example.com/big.jpg"]
