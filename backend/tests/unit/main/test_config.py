import re
from pathlib import Path

from eneo.main.config import Settings, get_settings


def _with_worker_capacity(settings: Settings, **updates: int | None) -> Settings:
    return settings.model_copy(update=updates)


def test_crawl_capacity_defaults_to_the_dedicated_worker_capacity() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=15,
        crawl_job_concurrency_limit=None,
    )

    assert settings.effective_crawl_job_concurrency_limit == 15


def test_single_slot_dedicated_worker_can_execute_one_crawl() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=1,
        crawl_job_concurrency_limit=None,
    )

    assert settings.effective_crawl_job_concurrency_limit == 1


def test_explicit_crawl_capacity_supports_multi_worker_clusters() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=15,
        crawl_job_concurrency_limit=30,
    )

    assert settings.effective_crawl_job_concurrency_limit == 30


def test_crawler_env_templates_only_publish_runtime_settings() -> None:
    backend_root = Path(__file__).parents[3]
    templates = (
        backend_root / ".env.template",
        backend_root.parent / "docs/deployment/env_backend.template",
    )
    crawler_names = {
        "DOWNLOAD_MAX_SIZE",
        "OBEY_ROBOTS",
        "AUTOTHROTTLE_ENABLED",
        "CLOSESPIDER_ITEMCOUNT",
        "WORKER_MAX_JOBS",
    }
    declared: set[str] = set()
    for template in templates:
        for name in re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", template.read_text()):
            if (
                name.startswith(("CRAWL_", "TENANT_WORKER_", "ORPHAN_CRAWL_"))
                or name in crawler_names
            ):
                declared.add(name)

    runtime_fields = Settings.model_fields
    assert declared
    assert {name for name in declared if name.lower() not in runtime_fields} == set()
