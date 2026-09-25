from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


collection_media = Table(
    "collection_media",
    Base.metadata,
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("media_id", ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True),
)

media_sources = Table(
    "media_sources",
    Base.metadata,
    Column("media_id", ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True),
)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ws"))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("workspace_slug", "canonical_url", name="uq_source_workspace_url"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("src"))
    workspace_slug: Mapped[str] = mapped_column(ForeignKey("workspaces.slug", ondelete="CASCADE"), index=True)
    original_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    platform_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    media: Mapped[list[MediaItem]] = relationship(secondary=media_sources, back_populates="sources")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("workspace_slug", "platform_media_id", name="uq_media_platform_id"),
        UniqueConstraint("workspace_slug", "sha256", name="uq_media_sha"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("med"))
    workspace_slug: Mapped[str] = mapped_column(ForeignKey("workspaces.slug", ondelete="CASCADE"), index=True)
    platform_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str] = mapped_column(String(20), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    sources: Mapped[list[Source]] = relationship(secondary=media_sources, back_populates="media")
    collections: Mapped[list[Collection]] = relationship(secondary=collection_media, back_populates="media")


class ContentRecord(Base):
    __tablename__ = "content_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("cnt"))
    workspace_slug: Mapped[str] = mapped_column(ForeignKey("workspaces.slug", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str | None] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), nullable=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    text: Mapped[str] = mapped_column(Text)


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("workspace_slug", "name", name="uq_collection_workspace_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("col"))
    workspace_slug: Mapped[str] = mapped_column(ForeignKey("workspaces.slug", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    media: Mapped[list[MediaItem]] = relationship(secondary=collection_media, back_populates="collections")


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("job"))
    workspace_slug: Mapped[str] = mapped_column(ForeignKey("workspaces.slug", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    auto_import: Mapped[bool] = mapped_column(Boolean, default=False)
    total_urls: Mapped[int] = mapped_column(Integer, default=0)
    scanned_urls: Mapped[int] = mapped_column(Integer, default=0)
    found_media: Mapped[int] = mapped_column(Integer, default=0)
    imported_media: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    items: Mapped[list[IngestJobItem]] = relationship(back_populates="job", cascade="all, delete-orphan")


class IngestJobItem(Base):
    __tablename__ = "ingest_job_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ji"))
    job_id: Mapped[str] = mapped_column(ForeignKey("ingest_jobs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[IngestJob] = relationship(back_populates="items")


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("key"))
    name: Mapped[str] = mapped_column(String(160))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    workspace_access: Mapped[str] = mapped_column(Text, default="*")
    scopes: Mapped[str] = mapped_column(String(200), default="read")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
