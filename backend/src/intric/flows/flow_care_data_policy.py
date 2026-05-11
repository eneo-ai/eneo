from __future__ import annotations

from typing import Mapping

from intric.flows.domain.flow import JsonObject
from intric.flows.flow_metadata import (
    FlowCareDataPolicyV1,
    FlowMetadataParseMode,
    parse_flow_metadata,
)


def resolve_flow_care_data_policy(
    metadata_json: JsonObject | Mapping[str, object] | None,
) -> FlowCareDataPolicyV1:
    return parse_flow_metadata(
        metadata_json, mode=FlowMetadataParseMode.PERSISTED_READ
    ).care_data_policy


def validate_flow_care_data_policy(
    metadata_json: JsonObject | Mapping[str, object] | None,
) -> None:
    parse_flow_metadata(metadata_json, mode=FlowMetadataParseMode.WRITE)
