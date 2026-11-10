from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, DEFAULT_QUEUE_NAME
from eneo.worker import run_cron
from eneo.worker.run_cron import (
    RegisteredCron,
    enqueue_cron,
    registered_crons,
    resolve_cron,
)


def _cron(name: str) -> Any:
    return SimpleNamespace(name=f"cron:{name}")


def test_registered_crons_strip_prefix_and_keep_queue() -> None:
    crons = registered_crons(
        {
            DEFAULT_QUEUE_NAME: [
                _cron("crawl_all_websites"),
                _cron("api_key_maintenance"),
            ],
            CRAWLER_QUEUE_NAME: [_cron("crawler_only")],
        }
    )

    assert crons == [
        RegisteredCron("crawler_only", CRAWLER_QUEUE_NAME),
        RegisteredCron("api_key_maintenance", DEFAULT_QUEUE_NAME),
        RegisteredCron("crawl_all_websites", DEFAULT_QUEUE_NAME),
    ]
    assert crons[-1].job_name == "cron:crawl_all_websites"


@pytest.mark.parametrize("requested", ["crawl_all_websites", "cron:crawl_all_websites"])
def test_resolve_cron_accepts_short_and_arq_names(requested: str) -> None:
    crons = [RegisteredCron("crawl_all_websites", DEFAULT_QUEUE_NAME)]

    assert resolve_cron(requested, crons) == crons[0]


def test_resolve_cron_rejects_unknown_name() -> None:
    with pytest.raises(LookupError, match="--list"):
        resolve_cron("nope", [RegisteredCron("crawl_all_websites", DEFAULT_QUEUE_NAME)])


async def test_enqueue_cron_targets_owning_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="job-1")),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(run_cron, "create_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(run_cron, "build_arq_redis_settings", lambda: object())

    job_id = await enqueue_cron(
        RegisteredCron("crawl_all_websites", CRAWLER_QUEUE_NAME)
    )

    assert job_id == "job-1"
    pool.enqueue_job.assert_awaited_once_with(
        "cron:crawl_all_websites", _queue_name=CRAWLER_QUEUE_NAME
    )
    pool.aclose.assert_awaited_once()


def test_main_lists_and_enqueues(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = [RegisteredCron("crawl_all_websites", DEFAULT_QUEUE_NAME)]
    monkeypatch.setattr(run_cron, "_load_registry", lambda: registry)
    enqueued: list[RegisteredCron] = []

    async def _fake_enqueue(cron: RegisteredCron) -> str:
        enqueued.append(cron)
        return "job-2"

    monkeypatch.setattr(run_cron, "enqueue_cron", _fake_enqueue)

    assert run_cron.main(["--list"]) == 0
    assert "crawl_all_websites" in capsys.readouterr().out

    assert run_cron.main(["unknown"]) == 2
    assert "Unknown cron job" in capsys.readouterr().err
    assert enqueued == []

    assert run_cron.main(["cron:crawl_all_websites"]) == 0
    assert enqueued == registry
    assert "job-2" in capsys.readouterr().out


def test_until_complete_needs_a_cron_that_can_show_completion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = [RegisteredCron("crawl_all_websites", DEFAULT_QUEUE_NAME)]
    monkeypatch.setattr(run_cron, "_load_registry", lambda: registry)
    monkeypatch.setattr(run_cron, "enqueue_cron", AsyncMock())

    assert run_cron.main(["--until-complete", "crawl_all_websites"]) == 2
    assert "--until-complete" in capsys.readouterr().err
    run_cron.enqueue_cron.assert_not_awaited()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_until_complete_runs_the_cron_here_and_returns_its_verdict(
    monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    """Never through the queue: the readback runs with the workers stopped."""
    registry = [RegisteredCron("run_retention", DEFAULT_QUEUE_NAME)]
    monkeypatch.setattr(run_cron, "_load_registry", lambda: registry)
    monkeypatch.setattr(run_cron, "enqueue_cron", AsyncMock())
    ran: list[str] = []

    def readback() -> int:
        ran.append("run_retention")
        return exit_code

    monkeypatch.setattr(
        run_cron, "_completion_checks", lambda: {"run_retention": readback}
    )

    assert run_cron.main(["--until-complete", "run_retention"]) == exit_code
    assert ran == ["run_retention"]
    run_cron.enqueue_cron.assert_not_awaited()


def test_the_retention_cron_can_show_completion() -> None:
    from eneo.main.retention_readback import main as retention_readback

    assert run_cron._completion_checks()["run_retention"] is retention_readback
