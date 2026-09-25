import os
from pathlib import Path

os.environ.setdefault("MEDIA_LIBRARY_DATA_DIR", "/tmp/media-library-tests")
os.environ.setdefault("MEDIA_LIBRARY_ADMIN_TOKEN", "test-admin")

import pytest

from app.config import get_settings
from app.database import Base, get_engine, init_db


@pytest.fixture(autouse=True)
def clean_db():
    root = Path(get_settings().data_dir)
    root.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(get_engine())
    with get_engine().begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS search_index")
    init_db()
    yield
