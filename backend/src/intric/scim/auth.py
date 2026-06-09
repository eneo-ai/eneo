import hashlib
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import get_session_with_transaction
from intric.database.tables.tenant_table import Tenants

_bearer = HTTPBearer(auto_error=False)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_scim_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session_with_transaction),
) -> UUID:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing SCIM bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_hash = _hash(credentials.credentials)
    result = await session.execute(
        select(Tenants.id).where(Tenants.scim_token_hash == token_hash)
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid SCIM bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant_id
