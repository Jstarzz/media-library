from datetime import datetime

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=160)


class JobCreate(BaseModel):
    workspace: str
    urls: list[str] = Field(min_length=1, max_length=500)
    auto_import: bool = False
    name: str | None = None


class CollectionCreate(BaseModel):
    workspace: str
    name: str
    description: str | None = None


class CollectionMediaAdd(BaseModel):
    media_ids: list[str] = Field(min_length=1)


class KeyCreate(BaseModel):
    name: str
    workspace_access: list[str] | str = "*"
    scopes: list[str] = ["read"]


class SourceOut(BaseModel):
    id: str
    workspace_slug: str
    original_url: str
    canonical_url: str | None
    platform: str
    title: str | None
    author: str | None
    caption: str | None
    published_at: datetime | None
    extractor: str | None

    model_config = {"from_attributes": True}
