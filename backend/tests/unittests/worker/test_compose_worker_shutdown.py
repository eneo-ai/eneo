"""Deployment compose must give arq workers time to drain before SIGKILL."""

import json
import re
from pathlib import Path

import yaml

from eneo.worker.worker import Worker

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE = REPO_ROOT / "docs/deployment/docker-compose.yml"
DOCKERFILE = REPO_ROOT / "backend/Dockerfile"
MARGIN_SECONDS = 5


def _seconds(value) -> float:
    parts = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", str(value))
    assert parts and any(parts.groups()), f"unparseable duration {value!r}"
    h, m, s = (int(p or 0) for p in parts.groups())
    return h * 3600 + m * 60 + s


def _is_arq_worker(service: dict) -> bool:
    env = service.get("environment") or []
    if isinstance(env, dict):
        env = [f"{k}={v}" for k, v in env.items()]
    command = service.get("command") or []
    if isinstance(command, str):
        command = command.split()
    return "RUN_AS_WORKER=true" in env or bool(
        command and command[0].endswith("-worker")
    )


def test_every_arq_worker_drains_before_docker_kills_it():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    workers = {n: s for n, s in services.items() if _is_arq_worker(s)}
    assert set(workers) >= {
        "worker",
        "task-execution-worker",
        "task-maintenance-worker",
        "crawler-worker",
    }

    minimum = Worker().job_completion_wait + MARGIN_SECONDS
    for name, service in workers.items():
        assert service.get("init") is True, f"{name}: init: true is required"
        grace = _seconds(service.get("stop_grace_period", "10s"))
        assert grace >= minimum, f"{name}: stop_grace_period {grace}s < {minimum}s"


def test_the_image_command_lets_init_signal_the_process_it_starts():
    # Workers without a command override start through the image's CMD. Under
    # `sh -c`, dash forks run.sh, so init's SIGTERM stops at the shell and the
    # worker is killed without draining; run.sh itself execs arq or gunicorn.
    (cmd,) = re.findall(r"^CMD\s+(.+)$", DOCKERFILE.read_text(), re.MULTILINE)
    argv = json.loads(cmd)
    assert argv == ["./run.sh"], f"backend image CMD {argv} must exec run.sh"
