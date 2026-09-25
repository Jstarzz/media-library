import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import APIKey


@dataclass(frozen=True)
class Principal:
    name: str
    workspaces: set[str] | None
    scopes: set[str]

    def can_access(self, workspace: str) -> bool:
        return self.workspaces is None or workspace in self.workspaces


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def generate_api_key() -> str:
    return "ml_" + secrets.token_urlsafe(32)


def _parse_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    return auth[7:].strip()


def principal_for_token(token: str, db: Session) -> Principal:
    settings = get_settings()
    if settings.admin_token and secrets.compare_digest(token, settings.admin_token):
        return Principal("company-admin", None, {"read", "ingest", "admin"})

    key = db.scalar(select(APIKey).where(APIKey.key_hash == hash_key(token), APIKey.active.is_(True)))
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    workspaces = None if key.workspace_access == "*" else set(filter(None, key.workspace_access.split(",")))
    scopes = set(filter(None, key.scopes.split(",")))
    return Principal(key.name, workspaces, scopes)


def require_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    return principal_for_token(_parse_bearer(request), db)


def require_scope(scope: str):
    def dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if scope not in principal.scopes and "admin" not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
        return principal
    return dependency


def assert_workspace(principal: Principal, workspace: str) -> None:
    if not principal.can_access(workspace):
        raise HTTPException(status_code=403, detail="API key cannot access this workspace")
