"""A space grants transcription services under the same rules as its models."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space
from eneo.transcription_services.models import TranscriptionServiceConnection


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        tenant_id=uuid4(),
        name=f"K{level}",
        description="",
        security_level=level,
        security_enabled=True,
    )


def _connection(level: int, *, enabled: bool = True) -> TranscriptionServiceConnection:
    now = datetime.now(timezone.utc)
    return TranscriptionServiceConnection(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"vemsa-{level}",
        endpoint_url="https://vemsa.example.se",
        is_enabled=enabled,
        security_classification=_classification(level),
        created_at=now,
        updated_at=now,
        space_count=0,
        last_check=None,
    )


def _space(classification, connections=(), *, personal: bool = False) -> Space:
    return Space(
        id=uuid4(),
        tenant_id=None,
        tenant_space_id=None,
        user_id=uuid4() if personal else None,
        name=MagicMock(),
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification,
        transcription_services=list(connections),
    )


def _ids(connections) -> list:
    return [connection.id for connection in connections]


def test_a_grant_below_the_classification_stays_but_is_not_usable():
    allowed, below = _connection(3), _connection(1)

    space = _space(_classification(3), [allowed, below])

    assert _ids(space.transcription_services) == [allowed.id]
    assert _ids(space.transcription_services_below_classification) == [below.id]
    assert _ids(space.linked_transcription_services) == [allowed.id, below.id]
    assert space.usable_transcription_service(allowed.id) == allowed
    assert space.usable_transcription_service(below.id) is None


def test_a_disabled_service_keeps_its_grant_but_takes_no_new_work():
    disabled = _connection(3, enabled=False)

    space = _space(_classification(3), [disabled])
    space.update(name="Renamed")

    assert _ids(space.linked_transcription_services) == [disabled.id]
    assert space.link_changes("transcription_service") == (set(), set())
    assert space.usable_transcription_service(disabled.id) is None


@pytest.mark.parametrize(
    "candidate, error",
    [
        (_connection(3, enabled=False), UnauthorizedException),
        (_connection(1), BadRequestException),
    ],
    ids=["disabled", "below-classification"],
)
def test_a_new_grant_must_be_enabled_and_meet_the_classification(candidate, error):
    space = _space(_classification(3))

    with pytest.raises(error):
        space.update(transcription_services=[candidate])


def test_a_grant_list_records_only_what_it_added_and_removed():
    kept, dropped, added = _connection(3), _connection(4), _connection(5)
    space = _space(_classification(3), [kept, dropped])

    space.update(transcription_services=[kept, added])

    assert space.link_changes("transcription_service") == ({added.id}, {dropped.id})


def test_raising_the_classification_removes_the_grants_it_no_longer_allows():
    low, high = _connection(2), _connection(5)
    space = _space(_classification(2), [low, high])

    space.update(security_classification=_classification(3))

    assert _ids(space.linked_transcription_services) == [high.id]
    assert space.link_changes("transcription_service") == (set(), {low.id})


def test_a_personal_space_cannot_be_granted_services():
    space = _space(None, personal=True)

    with pytest.raises(BadRequestException):
        space.update(transcription_services=[_connection(1)])
