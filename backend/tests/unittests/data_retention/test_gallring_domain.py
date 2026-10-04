from __future__ import annotations

from uuid import UUID

import pytest

from eneo.data_retention.domain.gallring import (
    GallringBudget,
    GallringUsage,
    InvalidReceiptTransition,
    ReceiptPhase,
    ReceiptReason,
    ReceiptState,
    gallring_batch_audit_id,
)

_P = ReceiptPhase
_FORWARD = {
    (_P.PENDING, _P.RELEASING),
    (_P.RELEASING, _P.DELETING),
    (_P.DELETING, _P.COMPLETED),
}


@pytest.mark.parametrize("source", [phase for phase in _P if phase != _P.PAUSED])
@pytest.mark.parametrize("target", list(_P))
def test_a_receipt_only_moves_forward_one_phase(source, target) -> None:
    reason = ReceiptReason.FILE_REFERENCED_ELSEWHERE if source == _P.STOPPED else None
    state = ReceiptState(phase=source, reason=reason)
    if (source, target) in _FORWARD:
        assert state.advance(target) == ReceiptState(phase=target)
    else:
        with pytest.raises(InvalidReceiptTransition):
            state.advance(target)


@pytest.mark.parametrize("phase", [_P.PENDING, _P.RELEASING, _P.DELETING])
def test_a_paused_receipt_is_unfinished_and_resumes_where_it_stopped(phase) -> None:
    paused = ReceiptState(phase=phase).pause(
        ReceiptReason.DERIVED_FILE_REFERENCED_ELSEWHERE
    )

    assert not paused.is_final
    assert paused.resume() == ReceiptState(phase=phase)
    with pytest.raises(InvalidReceiptTransition):
        paused.advance(_P.COMPLETED)


@pytest.mark.parametrize("final", [_P.COMPLETED, _P.STOPPED])
def test_final_receipts_neither_pause_nor_stop(final) -> None:
    reason = ReceiptReason.FILE_REFERENCED_ELSEWHERE if final == _P.STOPPED else None
    state = ReceiptState(phase=final, reason=reason)

    assert state.is_final
    for change in (state.pause, state.stop):
        with pytest.raises(InvalidReceiptTransition):
            change(ReceiptReason.FILE_REFERENCED_ELSEWHERE)


def test_budget_is_spent_by_any_limit() -> None:
    budget = GallringBudget(rows=10, files=5, seconds=60)

    assert budget.left(GallringUsage(rows=4, files=1), elapsed_seconds=1) == (
        GallringUsage(rows=6, files=4)
    )
    for used, elapsed in ((GallringUsage(rows=10), 1), (GallringUsage(files=5), 1)):
        assert budget.left(used, elapsed_seconds=elapsed) == GallringUsage()
    assert budget.left(GallringUsage(), elapsed_seconds=60) == GallringUsage()


def test_batch_audit_id_is_stable_per_batch_and_tenant() -> None:
    job, tenant = UUID(int=1), UUID(int=2)

    first = gallring_batch_audit_id(job_run_id=job, batch_seq=1, tenant_id=tenant)

    assert first == gallring_batch_audit_id(
        job_run_id=job, batch_seq=1, tenant_id=tenant
    )
    assert first != gallring_batch_audit_id(
        job_run_id=job, batch_seq=2, tenant_id=tenant
    )
