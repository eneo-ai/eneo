import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from eneo.jobs.job_manager import queue_name_for_task
from eneo.jobs.job_models import Task
from eneo.worker.arq import CrawlerWorkerSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
STACKS = {
    "deployment": REPO_ROOT / "docs" / "deployment" / "docker-compose.yml",
    "devcontainer": REPO_ROOT / ".devcontainer" / "docker-compose.yml",
    "e2e": REPO_ROOT / "docker-compose.e2e.yml",
    "e2e-ci": REPO_ROOT / "docker-compose.e2e.ci.yml",
}


def _environment(service: dict[str, Any]) -> dict[str, str | None]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {
            key: None if value is None else str(value)
            for key, value in environment.items()
        }
    entries = (entry.partition("=") for entry in environment)
    return {key: value if separator else None for key, separator, value in entries}


@pytest.mark.parametrize("stack", STACKS)
def test_every_supported_stack_starts_a_crawler_role_worker(stack: str) -> None:
    """Crawls are delivered to their own queue, so a stack without this service
    leaves every started crawl queued."""
    compose = yaml.safe_load(STACKS[stack].read_text())

    environment = _environment(compose["services"]["crawler-worker"])

    assert environment["RUN_AS_WORKER"] == "true"
    assert environment["WORKER_ROLE"] == "crawler"


def test_the_crawler_role_runs_the_settings_that_consume_the_crawl_queue() -> None:
    run_sh = (REPO_ROOT / "backend" / "run.sh").read_text()
    role = re.search(
        r'crawler\)\s+worker_settings="src\.eneo\.worker\.arq\.(\w+)"', run_sh
    )

    assert role is not None
    assert role.group(1) == "CrawlerWorkerSettings"
    assert CrawlerWorkerSettings["queue_name"] == queue_name_for_task(Task.CRAWL)


@pytest.mark.parametrize(
    ("service", "command"),
    [
        (
            "task-execution-worker",
            'bash -lc "cd /workspace/backend && .venv/bin/task-execution-worker"',
        ),
        (
            "task-maintenance-worker",
            'bash -lc "cd /workspace/backend && .venv/bin/task-maintenance-worker"',
        ),
        ("crawler-worker", 'bash -lc "cd /workspace/backend && exec ./run.sh"'),
    ],
)
def test_devcontainer_workers_restart_until_the_environment_is_installed(
    service: str, command: str
) -> None:
    """Compose starts the workers before post-create.sh has installed .venv. A
    worker that starts too early exits, and the restart policy retries it."""
    compose = yaml.safe_load(STACKS["devcontainer"].read_text())

    definition = compose["services"][service]

    assert definition["command"] == command
    assert definition["restart"] == "unless-stopped"
