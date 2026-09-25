import pytest

from app.storage import safe_filename
from app.urls import normalize_url, validate_public_url


def test_normalize_url_strips_fragment():
    assert normalize_url("HTTPS://Example.com/a#x") == "https://example.com/a"


def test_blocks_localhost():
    with pytest.raises(ValueError):
        validate_public_url("http://localhost:8000/private")


def test_safe_filename_removes_path_and_weird_chars():
    assert safe_filename("../../hello nasty?.jpg") == "hello-nasty-.jpg"
