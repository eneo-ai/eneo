"""Candidate factor and cap on the tenant rerank model payloads.

Both are optional: a create without them gets the measured defaults, an
update without them leaves the model unchanged. Values outside the ranges
are refused before they reach the database check.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.rerank_models.presentation.tenant_rerank_models_router import (
    TenantRerankModelCreate,
    TenantRerankModelUpdate,
)


def _create(**fields) -> TenantRerankModelCreate:
    return TenantRerankModelCreate(
        provider_id=uuid4(), name="rerank-v3.5", display_name="Cohere", **fields
    )


def test_create_defaults_to_the_measured_values():
    payload = _create()

    assert (payload.candidate_factor, payload.max_candidates) == (5, 100)


def test_create_and_update_accept_values_in_range():
    assert _create(candidate_factor=1, max_candidates=1000).max_candidates == 1000
    update = TenantRerankModelUpdate(candidate_factor=20, max_candidates=1)

    assert (update.candidate_factor, update.max_candidates) == (20, 1)


def test_update_without_the_fields_leaves_them_unset():
    update = TenantRerankModelUpdate(display_name="Renamed")

    assert "candidate_factor" not in update.model_fields_set
    assert "max_candidates" not in update.model_fields_set


@pytest.mark.parametrize(
    "fields",
    [
        {"candidate_factor": 0},
        {"candidate_factor": 21},
        {"max_candidates": 0},
        {"max_candidates": 1001},
    ],
)
def test_values_outside_the_ranges_are_refused(fields):
    with pytest.raises(ValidationError):
        _create(**fields)
    with pytest.raises(ValidationError):
        TenantRerankModelUpdate(**fields)
