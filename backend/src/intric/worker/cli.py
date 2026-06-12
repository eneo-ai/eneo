import sys

from arq.cli import cli

WORKER_SETTINGS = "src.intric.worker.arq.WorkerSettings"


def start() -> None:
    cli(args=[WORKER_SETTINGS, *sys.argv[1:]], prog_name="worker")
