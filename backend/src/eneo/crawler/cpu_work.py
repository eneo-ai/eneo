"""Keep crawler parsing and chunking responsive with at most two submitted jobs."""

from eneo.main.bounded_executor import BoundedExecutor

run_cpu_work = BoundedExecutor(2, "crawler-cpu").run
