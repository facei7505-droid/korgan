from fastapi import Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from .config import settings

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _role(key: str | None) -> str:
    role = settings.api_keys.get(key or "")
    if not role:
        raise HTTPException(401, "invalid or missing API key")
    return role


def require(*roles: str):
    """Dependency: caller's key must map to one of `roles` (admin always passes)."""

    def dep(header_key: str | None = Security(_header), key: str | None = Query(None, include_in_schema=False)) -> str:
        role = _role(header_key or key)
        if role != "admin" and role not in roles:
            raise HTTPException(403, f"role '{role}' not allowed")
        return role

    return Depends(dep)
