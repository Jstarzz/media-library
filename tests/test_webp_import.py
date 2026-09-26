from pathlib import Path

from PIL import Image

from app.storage import convert_to_webp, image_size


def test_jpeg_is_reencoded_as_webp_with_its_size(tmp_path: Path):
    source = tmp_path / "in.jpg"
    Image.new("RGB", (320, 200), (200, 30, 30)).save(source, "JPEG", quality=95)

    size = convert_to_webp(source, tmp_path / "out.webp", 82)

    assert size == (320, 200)
    with Image.open(tmp_path / "out.webp") as out:
        assert out.format == "WEBP"
    assert not (tmp_path / "out.webp.tmp").exists()


def test_png_transparency_survives(tmp_path: Path):
    source = tmp_path / "in.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 0)).save(source, "PNG")

    assert convert_to_webp(source, tmp_path / "out.webp", 82) == (40, 20)
    with Image.open(tmp_path / "out.webp") as out:
        assert out.convert("RGBA").getpixel((5, 5))[3] < 20


def test_exif_rotation_is_applied(tmp_path: Path):
    source = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (300, 100))
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90 CW on display
    image.save(source, "JPEG", exif=exif)

    assert image_size(source) == (100, 300)
    assert convert_to_webp(source, tmp_path / "out.webp", 82) == (100, 300)


def test_undecodable_file_returns_none_and_leaves_nothing(tmp_path: Path):
    source = tmp_path / "bad.jpg"
    source.write_bytes(b"not an image")

    assert convert_to_webp(source, tmp_path / "out.webp", 82) is None
    assert not (tmp_path / "out.webp").exists()
    assert not (tmp_path / "out.webp.tmp").exists()
    assert image_size(source) is None
