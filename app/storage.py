import hashlib
import mimetypes
import re
import subprocess
from pathlib import Path

from PIL import Image

from app.config import get_settings


SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_filename(name: str, fallback: str = "media") -> str:
    name = Path(name).name.strip().replace("\x00", "")
    name = SAFE_NAME.sub("-", name).strip(".-")
    return (name[:180] or fallback)


def extension_for(mime_type: str | None, url: str) -> str:
    ext = mimetypes.guess_extension((mime_type or "").split(";")[0].strip()) if mime_type else None
    if not ext:
        ext = Path(url.split("?", 1)[0]).suffix
    return ext.lower()[:10] if ext and ext.startswith(".") else ".bin"


class LocalStorageProvider:
    def __init__(self):
        self.root = get_settings().data_dir

    def workspace_dir(self, workspace: str) -> Path:
        path = self.root / "workspaces" / safe_filename(workspace)
        for child in ("media", "thumbnails", "exports"):
            (path / child).mkdir(parents=True, exist_ok=True)
        return path

    def media_path(self, workspace: str, source_id: str, index: int, remote_url: str, ext: str) -> Path:
        digest = hashlib.sha256(remote_url.encode()).hexdigest()[:10]
        return self.workspace_dir(workspace) / "media" / f"{source_id}_{index:03d}_{digest}{ext}"

    def thumbnail_path(self, workspace: str, media_id: str) -> Path:
        return self.workspace_dir(workspace) / "thumbnails" / f"{media_id}.webp"

    def make_thumbnail(self, source: Path, destination: Path, media_type: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if media_type == "image":
            with Image.open(source) as image:
                image.thumbnail((640, 640))
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGB")
                image.save(destination, "WEBP", quality=82)
            return
        if media_type == "video":
            subprocess.run([
                "ffmpeg", "-y", "-ss", "00:00:01", "-i", str(source),
                "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", str(destination)
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
