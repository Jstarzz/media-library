import json
import zipfile

from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Collection, MediaItem, Source, Workspace
from app.services.exports import create_export
from app.storage import LocalStorageProvider


def test_export_zip_contains_manifest_metadata_and_files():
    storage = LocalStorageProvider()
    media_dir = storage.workspace_dir("dte") / "media"
    media_path = media_dir / "sample.jpg"
    media_path.write_bytes(b"fake-jpeg-bytes")

    with Session(get_engine()) as db:
        db.add(Workspace(slug="dte", name="DTE"))
        source = Source(
            workspace_slug="dte",
            original_url="https://example.com/post/1",
            canonical_url="https://example.com/post/1",
            platform="facebook",
            caption="Carnival highlights",
            author="DTE",
        )
        media = MediaItem(
            workspace_slug="dte",
            media_type="image",
            mime_type="image/jpeg",
            local_path=str(media_path),
            filename="sample.jpg",
            file_size=media_path.stat().st_size,
            sha256="a" * 64,
        )
        media.sources.append(source)
        collection = Collection(workspace_slug="dte", name="Carnival 2026")
        collection.media.append(media)
        db.add_all([source, media, collection])
        db.commit()

        export = create_export(db, "dte", collection_id=collection.id)

    with zipfile.ZipFile(export.local_path) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        assert any(name.endswith("/metadata.json") for name in names)
        asset_name = next(name for name in names if name.endswith(".jpg"))
        assert archive.read(asset_name) == b"fake-jpeg-bytes"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["workspace"] == "dte"
        assert manifest["media"][0]["caption"] == "Carnival highlights"
