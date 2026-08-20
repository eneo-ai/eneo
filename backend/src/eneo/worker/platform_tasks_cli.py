import sys

from arq.cli import cli

EXECUTION_WORKER_SETTINGS = "eneo.worker.platform_tasks.PlatformExecutionWorkerSettings"
MAINTENANCE_WORKER_SETTINGS = (
    "eneo.worker.platform_tasks.PlatformMaintenanceWorkerSettings"
)


def execution_worker() -> None:
    cli(
        args=[EXECUTION_WORKER_SETTINGS, *sys.argv[1:]],
        prog_name="task-execution-worker",
    )


def maintenance_worker() -> None:
    cli(
        args=[MAINTENANCE_WORKER_SETTINGS, *sys.argv[1:]],
        prog_name="task-maintenance-worker",
    )
