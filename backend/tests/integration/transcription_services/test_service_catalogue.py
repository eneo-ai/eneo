"""Space editors see the organisation's speaker services by name only."""

from __future__ import annotations

import pytest

from tests.integration.transcription_services.conftest import BASE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CATALOGUE = "/api/v1/transcription-services/"


async def test_any_member_lists_service_names_without_addresses_or_keys(
    client, member_headers, create_connection
):
    created = await create_connection(name="Vemsa Sundsvall")

    listed = await client.get(CATALOGUE, headers=member_headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == [
        {
            "id": created["id"],
            "name": "Vemsa Sundsvall",
            "is_enabled": True,
            "security_classification": None,
        }
    ]
    # The administrator routes, with addresses, stay closed to members.
    assert (await client.get(BASE, headers=member_headers)).status_code == 403
