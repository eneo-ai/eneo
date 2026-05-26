"""Unit tests for `resolve_tenant_security_classification`.

The helper is the single point of enforcement for "is this classification
reachable by this tenant" across the three tenant model routers, so we keep
fast unit coverage here in addition to the integration tests in
`tests/integration/test_tenant_models_security_classification.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.main.exceptions import NotFoundException
from intric.main.models import ModelId
from intric.security_classifications.tenant_validation import (
    resolve_tenant_security_classification,
)


def _session_returning(scalar_value):
    """Build a minimal async session whose `execute(...).scalar_one_or_none()`
    returns the given value. Avoids a real DB by skipping everything else."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_returns_none_when_reference_is_none():
    session = MagicMock()
    session.execute = AsyncMock()  # would fail the test if invoked

    result = await resolve_tenant_security_classification(
        session, reference=None, tenant_id=uuid4()
    )

    assert result is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_returns_classification_id_when_match():
    classification_id = uuid4()
    session = _session_returning(classification_id)

    result = await resolve_tenant_security_classification(
        session,
        reference=ModelId(id=classification_id),
        tenant_id=uuid4(),
    )

    assert result == classification_id
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_raises_when_classification_not_found():
    session = _session_returning(None)

    with pytest.raises(NotFoundException):
        await resolve_tenant_security_classification(
            session,
            reference=ModelId(id=uuid4()),
            tenant_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_cross_tenant_reference_treated_as_not_found():
    """A classification that exists in another tenant is invisible from
    here — the WHERE clause filters by tenant_id, so the lookup returns
    None and we raise the same NotFoundException as for a wholly missing id.
    The router never sees the difference, which is the desired behaviour."""
    session = _session_returning(None)

    with pytest.raises(NotFoundException):
        await resolve_tenant_security_classification(
            session,
            reference=ModelId(id=uuid4()),
            tenant_id=uuid4(),
        )
