"""The suite keeps no more Flow runs in flight than the tenant can carry.

A run holds one of the suite's run slots from its creation until it is
terminal or cancelled. Planning and Builder turns are not limited, and a 429
from run creation is the server's answer, recorded and never retried.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import time
from pathlib import Path
from threading import Barrier, BoundedSemaphore, Lock
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.error import HTTPError

from pytest import MonkeyPatch, mark, raises

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "ai_builder_api_battle_test.py"
)


def _battle_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ai_builder_api_battle_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _RunApi:
    """A Flow API that counts runs in flight: created and not yet terminal."""

    def __init__(
        self,
        harness: ModuleType,
        monkeypatch: MonkeyPatch,
        *,
        create_error: HTTPError | None = None,
        drive_error: Exception | None = None,
        cancel_error: HTTPError | None = None,
    ) -> None:
        self.lock = Lock()
        self.in_flight = 0
        self.peak = 0
        self.posts = 0
        self.cancels = 0
        self.create_error = create_error
        self.drive_error = drive_error
        self.cancel_error = cancel_error
        monkeypatch.setattr(harness, "_request_json", self.request_json)
        monkeypatch.setattr(harness, "_drive_run", self.drive_run)
        monkeypatch.setattr(harness, "_read_final_file", lambda **_: None)

    def request_json(self, *, method: str, path: str, **_: object) -> dict[str, Any]:
        if path.endswith("/publish/"):
            return {"published_version": 4}
        if path.endswith("/run-contract/"):
            return {"published_flow_version": 4}
        if path.endswith("/runs/") and method == "POST":
            with self.lock:
                self.posts += 1
                if self.create_error is not None:
                    raise self.create_error
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
            return {"id": "run-1", "status": "queued"}
        if "cancel" in path:
            with self.lock:
                self.cancels += 1
                if self.cancel_error is not None:
                    raise self.cancel_error
                self.in_flight -= 1
            return {"status": "cancelled"}
        if path.endswith("/evidence/"):
            return {"step_results": []}
        raise AssertionError((method, path))

    def drive_run(self, **_: object) -> dict[str, Any]:
        time.sleep(0.02)
        if self.drive_error is not None:
            raise self.drive_error
        with self.lock:
            self.in_flight -= 1
        return {"status": "completed"}


def _execute(
    harness: ModuleType,
    config: Any,
    record: dict[str, Any],
    *,
    timeout_seconds: float = 60,
) -> object:
    return harness._execute_and_collect_runtime_evidence(
        config=config,
        flow_id="flow-1",
        execution=SimpleNamespace(
            inputs=harness.ExecutionInputs(text="Skriv beslutet."), checkpoints=()
        ),
        runtime_file_paths=(),
        timeout_seconds=timeout_seconds,
        artifact_output_dir=Path("/nonexistent"),
        case_id="slot-case",
        record=record,
    )


def _config(harness: ModuleType, slots: BoundedSemaphore, **extra: Any) -> Any:
    return harness.ApiConfig(
        base_url="http://localhost/api/v1",
        api_key="k",
        timeout_seconds=30,
        run_slots=slots,
        **extra,
    )


def test_eight_observations_share_four_run_slots_while_planning_in_parallel(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    api = _RunApi(harness, monkeypatch)
    config = _config(harness, BoundedSemaphore(4))
    # Every observation must be planning at once to pass this barrier, so a
    # scheduler that serialised planning would break it.
    planning = Barrier(8, timeout=5)

    def acquire(observation: tuple[int, int, Any]) -> dict[str, Any]:
        planning.wait()
        return {"evidence": _execute(harness, config, {})}

    results = harness._acquire_observations_with_case_isolation(
        observations=[
            (1, index, SimpleNamespace(case_id=f"case-{index}")) for index in range(8)
        ],
        max_concurrency=8,
        acquire=acquire,
    )

    assert len(results) == 8
    assert api.posts == 8
    assert api.peak == 4
    assert api.in_flight == 0


@mark.parametrize("ending", ["completed", "create_refused", "cancelled"])
def test_a_run_slot_is_released_however_the_run_ends(
    monkeypatch: MonkeyPatch, ending: str
) -> None:
    harness = _battle_harness()
    refusal = HTTPError(
        "http://localhost/runs/",
        429,
        "refused",
        None,  # type: ignore[arg-type]
        io.BytesIO(b'{"code": "flow_run_concurrency_limit_reached"}'),
    )
    api = _RunApi(
        harness,
        monkeypatch,
        create_error=refusal if ending == "create_refused" else None,
        drive_error=RuntimeError("run failed") if ending == "cancelled" else None,
    )
    slots = BoundedSemaphore(1)
    record: dict[str, Any] = {}

    if ending == "completed":
        _execute(harness, _config(harness, slots), record)
    else:
        with raises((HTTPError, RuntimeError)):
            _execute(harness, _config(harness, slots), record)

    assert slots.acquire(blocking=False)
    assert api.cancels == (1 if ending == "cancelled" else 0)
    if ending == "create_refused":
        # The server's 429 is kept and raised; it is never retried.
        assert api.posts == 1
        assert record["run_request_refused"]["status_code"] == 429


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        "http://localhost/x/",
        code,
        "refused",
        None,
        io.BytesIO(b"{}"),  # type: ignore[arg-type]
    )


def test_a_failed_cancel_retires_the_slot_instead_of_freeing_it(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    api = _RunApi(
        harness,
        monkeypatch,
        drive_error=RuntimeError("run failed"),
        cancel_error=_http_error(503),
    )
    slots = BoundedSemaphore(1)
    first: dict[str, Any] = {}

    with raises(RuntimeError):
        _execute(harness, _config(harness, slots), first)
    # The run may still be active, so the next observation must not get its
    # slot: it waits out its deadline and never creates a run.
    with raises(harness.ObservationDeadlineExceeded):
        _execute(harness, _config(harness, slots, deadline=time.monotonic() + 0.05), {})

    assert first["run_slot_retired"] is True
    assert (api.posts, api.cancels) == (1, 1)


@mark.parametrize("bound", ["observation_deadline", "run_timeout"])
def test_waiting_for_a_run_slot_is_bounded(
    monkeypatch: MonkeyPatch, bound: str
) -> None:
    harness = _battle_harness()
    api = _RunApi(harness, monkeypatch)
    slots = BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    # Each variant sets only its own bound short; the other would hang.
    by_deadline = bound == "observation_deadline"
    extra = {"deadline": time.monotonic() + 0.05} if by_deadline else {}

    with raises(harness.ObservationDeadlineExceeded):
        _execute(
            harness,
            _config(harness, slots, **extra),
            {},
            timeout_seconds=600 if by_deadline else 0.05,
        )

    assert api.posts == 0


def _executing_case(harness: ModuleType) -> Any:
    return harness.BattleCase(
        case_id="runs",
        prompt="Build it.",
        apply_plan=True,
        execution=SimpleNamespace(),
    )


def test_an_expired_observation_frees_the_slot_it_took_without_a_run(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    api = _RunApi(harness, monkeypatch)
    slots = BoundedSemaphore(1)
    record: dict[str, Any] = {}

    with raises(harness.ObservationDeadlineExceeded):
        _execute(
            harness, _config(harness, slots, deadline=time.monotonic() - 1), record
        )

    assert slots.acquire(blocking=False)
    assert api.posts == 0
    assert "run_slot_retired" not in record


_IDLE_TENANT = {"max_concurrent_runs": 4, "active_runs": 0, "available_slots": 4}


def _slots_from_reading(
    harness: ModuleType, monkeypatch: MonkeyPatch, reading: object
) -> tuple[int | None, list[str]]:
    """Slots for an executing suite without a preflight, reading `reading`."""

    paths: list[str] = []

    def request_json(*, method: str, path: str, **_: object) -> object:
        paths.append(f"{method} {path}")
        if isinstance(reading, Exception):
            raise reading
        return reading

    monkeypatch.setattr(harness, "_request_json", request_json)
    slots = harness._suite_run_slots(
        config=None, cases=[_executing_case(harness)], capacity_preflight=None
    )
    return slots, paths


def test_run_slots_reuse_the_preflight_capacity_without_reading_again(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(harness, "_request_json", None)

    assert (
        harness._suite_run_slots(
            config=None,
            cases=[_executing_case(harness)],
            capacity_preflight={"runtime_capacity": _IDLE_TENANT},
        )
        == 4
    )


def test_a_suite_without_a_preflight_reads_the_tenant_capacity(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()

    assert _slots_from_reading(harness, monkeypatch, _IDLE_TENANT) == (
        4,
        ["GET /flows/runs/capacity/"],
    )


@mark.parametrize(
    ("reading", "refusal"),
    [
        (
            {"max_concurrent_runs": 4, "active_runs": 4, "available_slots": 0},
            "measurement_tenant_not_idle",
        ),
        ({"max_concurrent_runs": "four", "active_runs": 0}, "runtime_capacity_unknown"),
    ],
)
def test_a_busy_tenant_or_an_invalid_reading_refuses_the_suite(
    monkeypatch: MonkeyPatch, reading: dict[str, object], refusal: str
) -> None:
    harness = _battle_harness()

    with raises(harness.CapacityPreflightRefused) as caught:
        _slots_from_reading(harness, monkeypatch, reading)

    assert caught.value.verdict["refusals"] == [refusal]
    assert harness.harness_failure_class(caught.value) == "harness_configuration"


def test_a_capacity_outage_keeps_its_own_failure_class(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    outage = _http_error(503)

    with raises(HTTPError) as caught:
        _slots_from_reading(harness, monkeypatch, outage)

    assert caught.value is outage
    assert harness.harness_failure_class(caught.value) == "dependency_stack"
