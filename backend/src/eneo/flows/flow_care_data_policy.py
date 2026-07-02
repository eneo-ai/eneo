from __future__ import annotations

from typing import Mapping

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_metadata import (
    FlowCareDataPolicy,
    FlowMetadataParseMode,
    parse_flow_metadata,
)


def resolve_flow_care_data_policy(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
) -> FlowCareDataPolicy:
    return parse_flow_metadata(
        metadata_json, mode=FlowMetadataParseMode.PERSISTED_READ
    ).care_data_policy
