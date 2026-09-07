"""Disposable bridge rehearsal: released schema, real process death, API and restore.

Run explicitly with ``pytest -m migration_isolation``. The default smoke profile
is small; ``ENEO_FILE_ICON_REHEARSAL_PROFILE=capacity`` includes a 200 MiB item.
``ENEO_FILE_ICON_REHEARSAL_OUTPUT`` optionally saves the bounded JSON report.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import UUID, uuid4

import psycopg2
import pytest
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

from alembic import command
from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.main.config import set_settings
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)
from eneo.object_content.file_icon_preflight import run_file_icon_preflight
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand
from tests.integration.object_content.test_file_original_download import (
    _signed_download,
)

cleanup_database = expand.cleanup_database
seed_default_models = expand.seed_default_models
encryption_service = expand.encryption_service

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_MIB = 1024 * 1024
_RELEASED_REVISION = "3eb6a34b6733"
_BRIDGE_REVISION = "202609071000"
_BARRIER = 793_202_609
_PROFILE = os.environ.get("ENEO_FILE_ICON_REHEARSAL_PROFILE", "smoke")
assert _PROFILE in {"smoke", "capacity"}


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    ).with_kwargs(mem_limit="2g", nano_cpus=2_000_000_000) as postgres:
        yield postgres


def _connect(url):
    return psycopg2.connect(
        url.replace("+psycopg2", "").replace("+asyncpg", ""), connect_timeout=5
    )


def _sample_database(postgres, url, stop):
    """Sample only the disposable database container, including backup activity."""
    samples = []
    container = postgres.get_wrapped_container()
    with _connect(url) as connection, connection.cursor() as cursor:
        connection.autocommit = True
        cursor.execute("SET statement_timeout = '5s'")
        while True:
            cursor.execute(
                "SELECT pg_current_wal_insert_lsn(), pg_database_size(current_database()), "
                "(SELECT sum(size) FROM pg_ls_waldir()), "
                "(SELECT temp_bytes FROM pg_stat_database WHERE datname=current_database())"
            )
            lsn, database_bytes, retained_wal, temp_bytes = cursor.fetchone()
            stats = container.stats(stream=False)
            memory = stats["memory_stats"]
            # cgroup v2 exposes anonymous resident memory as anon; v1 uses rss.
            rss = memory["stats"].get("anon", memory["stats"].get("rss"))
            assert rss is not None, memory
            free = container.exec_run("df -Pk /var/lib/postgresql/data /tmp")
            assert free.exit_code == 0, free.output
            free_bytes = [
                int(line.split()[3]) * 1024 for line in free.output.splitlines()[1:]
            ]
            samples.append(
                {
                    "lsn": lsn,
                    "database_bytes": database_bytes,
                    "retained_wal_bytes": int(retained_wal),
                    "temporary_query_bytes": temp_bytes,
                    "rss_bytes": rss,
                    "container_memory_bytes": memory["usage"],
                    "cpu_seconds": stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1e9,
                    "free_bytes": min(free_bytes),
                }
            )
            if stop.wait(0.5):
                break
        cursor.execute(
            "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(), %s)",
            (samples[0]["lsn"],),
        )
        generated_wal = int(cursor.fetchone()[0])
    return {
        "samples": len(samples),
        "nominal_sample_interval_seconds": 0.5,
        "rss_peak_bytes": max(item["rss_bytes"] for item in samples),
        "container_memory_peak_bytes": max(
            item["container_memory_bytes"] for item in samples
        ),
        "cpu_seconds": samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"],
        "database_peak_bytes": max(item["database_bytes"] for item in samples),
        "temporary_query_bytes": samples[-1]["temporary_query_bytes"],
        "minimum_volume_free_bytes": min(item["free_bytes"] for item in samples),
        "generated_wal_bytes": generated_wal,
        "retained_wal_peak_bytes": max(item["retained_wal_bytes"] for item in samples),
        "scope": "disposable PostgreSQL container; sampled peaks can miss shorter transients",
    }


@pytest.fixture(scope="session")
def database_measurements(test_settings, postgres_container):
    stop = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            _sample_database, postgres_container, test_settings.sync_database_url, stop
        )
        try:
            yield stop, result
        finally:
            stop.set()
            result.result(timeout=15)


def _dump(postgres, database_name, path):
    with path.open("wb") as output:
        subprocess.run(
            [
                "docker",
                "exec",
                postgres.get_wrapped_container().id,
                "pg_dump",
                "-U",
                "integration_test_user",
                "-Fc",
                "-d",
                database_name,
            ],
            stdout=output,
            stderr=subprocess.PIPE,
            check=True,
        )


def _restore(postgres, path, database_name):
    prefix = ["docker", "exec", postgres.get_wrapped_container().id]
    subprocess.run(
        [*prefix, "createdb", "-U", "integration_test_user", database_name],
        capture_output=True,
        check=True,
    )
    with path.open("rb") as source:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                postgres.get_wrapped_container().id,
                "pg_restore",
                "--exit-on-error",
                "-U",
                "integration_test_user",
                "-d",
                database_name,
            ],
            stdin=source,
            capture_output=True,
            check=True,
        )


def _seed_sources(url):
    from init_db import add_tenant_user

    with _connect(url) as connection:
        add_tenant_user(
            connection,
            "test_tenant",
            1_000_000,
            "test_user",
            "test@example.com",
            "test_password",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id, id FROM users WHERE email='test@example.com'"
            )
            tenant_id, user_id = cursor.fetchone()
            files = []
            workload = [("text", "small text åäö".encode(), b"original text")]
            workload += [("image", b"", None), ("text", b"", b"")]
            workload += [("image", b"small image" * 64, None)] * (
                256 if _PROFILE == "capacity" else 16
            )
            workload += [("audio", b"audio" * 4096, None)]
            if _PROFILE == "capacity":
                random_mib = random.Random(793).randbytes(_MIB)
                workload += [("image", random_mib, None)] * 8
                workload += [("image", b"a" * _MIB, None)] * 8
                workload += [("image", random_mib * 200, None)]
            for index, (file_type, payload, original) in enumerate(workload):
                file_id = str(uuid4())
                is_text = file_type == "text"
                cursor.execute(
                    "INSERT INTO files (id, name, text, blob, checksum, size, "
                    "mimetype, file_type, transcription, user_id, tenant_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        file_id,
                        f"legacy-{index}",
                        payload.decode() if is_text else None,
                        original if is_text else payload,
                        sha256(payload).hexdigest(),
                        len(payload),
                        "text/plain" if is_text else "application/octet-stream",
                        file_type,
                        "transcribed åäö" if file_type == "audio" else None,
                        user_id,
                        tenant_id,
                    ),
                )
                if len(payload) < _MIB:
                    files.append((file_id, payload))
            icon_id = str(uuid4())
            cursor.execute(
                "INSERT INTO icons (id, blob, mimetype, size, tenant_id) "
                "VALUES (%s, %s, 'image/png', 10, %s)",
                (icon_id, b"icon bytes", tenant_id),
            )
    return files, icon_id


def _source_facts(url):
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT owner_kind, id::text, source_column, octet_length(payload), sha256(payload) "
            "FROM (SELECT 'file' AS owner_kind, id, 'text' AS source_column, "
            "convert_to(text, 'UTF8') AS payload FROM files WHERE text IS NOT NULL "
            "UNION ALL SELECT 'file', id, 'blob', blob FROM files WHERE blob IS NOT NULL "
            "UNION ALL SELECT 'file', id, 'transcription', convert_to(transcription, 'UTF8') "
            "FROM files WHERE transcription IS NOT NULL "
            "UNION ALL SELECT 'icon', id, 'blob', blob FROM icons WHERE blob IS NOT NULL) sources "
            "ORDER BY owner_kind, id, source_column"
        )
        return [(*key, bytes(digest).hex()) for *key, digest in cursor]


def _assert_adopted(url):
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM file_icon_backfill_items i "
            "LEFT JOIN object_contents c ON c.id=i.content_id "
            "LEFT JOIN inline_content_payloads p ON p.content_id=c.id "
            "LEFT JOIN file_content_references f ON i.owner_kind='file' "
            "AND f.file_id=i.owner_id AND f.variant=i.variant AND f.ordinal=i.ordinal "
            "LEFT JOIN icon_content_references icon ON i.owner_kind='icon' "
            "AND icon.icon_id=i.owner_id AND icon.variant=i.variant AND i.ordinal=0 "
            "WHERE i.state <> 'done' OR c.state IS DISTINCT FROM 'available' "
            "OR coalesce(f.content_id, icon.content_id) IS DISTINCT FROM i.content_id "
            "OR sha256(p.payload) IS DISTINCT FROM c.sha256 "
            "OR octet_length(p.payload) IS DISTINCT FROM c.size_bytes"
        )
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT state FROM file_icon_backfill_campaign")
        assert cursor.fetchone() == ("complete",)
        cursor.execute(
            "WITH sources AS ("
            "SELECT 'file' AS owner_kind, id AS owner_id, CASE "
            "WHEN file_type='text' THEN 'extracted_text' WHEN file_type='audio' THEN 'original' "
            "WHEN parent_file_id IS NOT NULL THEN 'derived_page' ELSE 'legacy_image' END AS variant, "
            "CASE WHEN file_type='text' THEN convert_to(text, 'UTF8') ELSE blob END AS payload "
            "FROM files WHERE CASE WHEN file_type='text' THEN text IS NOT NULL ELSE blob IS NOT NULL END "
            "UNION ALL SELECT 'file', id, 'original', blob FROM files WHERE file_type='text' AND blob IS NOT NULL "
            "UNION ALL SELECT 'file', id, 'transcription', convert_to(transcription, 'UTF8') "
            "FROM files WHERE transcription IS NOT NULL "
            "UNION ALL SELECT 'icon', id, 'primary', blob FROM icons WHERE blob IS NOT NULL) "
            "SELECT count(*) FROM sources s LEFT JOIN file_icon_backfill_items i "
            "ON i.owner_kind=s.owner_kind AND i.owner_id=s.owner_id AND i.variant=s.variant AND i.ordinal=0 "
            "LEFT JOIN object_contents c ON c.id=i.content_id "
            "WHERE c.sha256 IS DISTINCT FROM sha256(s.payload) "
            "OR c.size_bytes IS DISTINCT FROM octet_length(s.payload)"
        )
        assert cursor.fetchone() == (0,)


@pytest.fixture(scope="session")
async def setup_database(test_settings, postgres_container, database_measurements):
    url = test_settings.sync_database_url
    config = expand._alembic_config(url)
    started = time.perf_counter()
    command.upgrade(config, _RELEASED_REVISION)
    files, icon_id = _seed_sources(url)
    expected_sources = _source_facts(url)
    preflight_started = time.perf_counter()
    preflight = await run_file_icon_preflight(url)
    assert preflight.outcome == "ready", preflight.blockers
    report = {
        "profile": _PROFILE,
        "postgres_image": expand._POSTGRES_13_IMAGE,
        "postgres_cpu_limit": 2,
        "postgres_memory_limit_bytes": 2 * 1024 * _MIB,
        "source_revision": _RELEASED_REVISION,
        "bridge_revision": _BRIDGE_REVISION,
        "preflight_seconds": time.perf_counter() - preflight_started,
        "preflight": asdict(preflight),
        "replicas": "not deployed in this isolated profile",
        "object_store": "not configured; PostgreSQL-only profile",
        "acceptance": {
            "byte_or_reference_mismatches": 0,
            "failed_api_requests": 0,
            "maximum_rehearsal_seconds": 300,
            "maximum_worker_rss_bytes": 512 * _MIB,
            "minimum_database_volume_free_bytes": 512 * _MIB,
        },
    }
    with TemporaryDirectory(prefix="eneo-bridge-rehearsal-") as temporary:
        path = Path(temporary)
        _dump(postgres_container, test_settings.postgres_db, path / "before.dump")
        upgrade_started = time.perf_counter()
        command.upgrade(config, _BRIDGE_REVISION)
        report["expand_inventory_seconds"] = time.perf_counter() - upgrade_started
        assert _source_facts(url) == expected_sources
        sessionmanager.init(test_settings.database_url)
        try:
            yield {
                "files": files,
                "icon_id": icon_id,
                "report": report,
                "path": path,
                "expected_sources": expected_sources,
                "started": started,
            }
        finally:
            await sessionmanager.close()


def _start_worker(url, path, *, lease_seconds):
    environment = os.environ.copy()
    environment.update(
        ENEO_REHEARSAL_CHILD_DATABASE=make_url(url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False),
        ENEO_REHEARSAL_CHILD_OUTPUT=str(path),
        ENEO_REHEARSAL_CHILD_LEASE=str(lease_seconds),
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(Path(__file__).resolve().parents[3]), environment.get("PYTHONPATH")),
        )
    )
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve())],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


async def _wait_for_copy_lock(url, blocker_pid, process):
    async with asyncio.timeout(30):
        while process.poll() is None:
            with _connect(url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE %s = ANY(pg_blocking_pids(pid))) AND EXISTS "
                    "(SELECT 1 FROM file_icon_backfill_items WHERE state='leased')",
                    (blocker_pid,),
                )
                if cursor.fetchone() == (True,):
                    return
            await asyncio.sleep(0.05)
    raise AssertionError("Worker exited before reaching the copy barrier")


async def test_released_upgrade_recovers_from_process_death_and_backup_restore(
    setup_database,
    postgres_container,
    test_settings,
    client,
    db_container,
    admin_user_api_key,
    database_measurements,
):
    state = setup_database
    url = test_settings.sync_database_url
    report = state["report"]
    path = state["path"]
    killed = worker = None
    try:
        with _connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                f"CREATE FUNCTION rehearsal_block_copy() RETURNS trigger LANGUAGE plpgsql "
                f"AS $$ BEGIN PERFORM pg_advisory_xact_lock({_BARRIER}); RETURN NEW; END $$; "
                "CREATE TRIGGER rehearsal_block_copy BEFORE INSERT ON inline_content_payloads "
                "FOR EACH ROW EXECUTE FUNCTION rehearsal_block_copy()"
            )
        with _connect(url) as blocker, blocker.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s), pg_backend_pid()", (_BARRIER,))
            blocker_pid = cursor.fetchone()[1]
            killed = _start_worker(url, path / "killed.json", lease_seconds=2)
            await _wait_for_copy_lock(url, blocker_pid, killed)
            killed.kill()
            await asyncio.to_thread(killed.wait, timeout=5)
            assert killed.returncode == -9
            cursor.execute("SELECT pg_advisory_unlock(%s)", (_BARRIER,))
        with _connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute(
                "DROP TRIGGER rehearsal_block_copy ON inline_content_payloads"
            )
            cursor.execute("DROP FUNCTION rehearsal_block_copy()")
            cursor.execute("SELECT count(*) FROM inline_content_payloads")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM file_icon_backfill_items WHERE state='leased'"
            )
            assert cursor.fetchone()[0] > 0
        report["process_death"] = (
            "SIGKILL while the payload INSERT was uncommitted; no partial payload published"
        )

        durations = []
        uploaded = []
        headers = {"X-API-Key": admin_user_api_key.key}
        async with db_container():
            worker = _start_worker(url, path / "worker.json", lease_seconds=300)
            async with asyncio.timeout(300):
                round_number = 0
                while worker.poll() is None or round_number < 8:
                    started = time.perf_counter()
                    file_id, expected = state["files"][
                        round_number % len(state["files"])
                    ]
                    response = await _signed_download(
                        client, headers, UUID(file_id), original=False
                    )
                    assert response.status_code == 200 and response.content == expected
                    durations.append(time.perf_counter() - started)
                    started = time.perf_counter()
                    icon = await client.get(f"/api/v1/icons/{state['icon_id']}/")
                    assert icon.status_code == 200 and icon.content == b"icon bytes"
                    durations.append(time.perf_counter() - started)
                    payload = f"new upload {round_number}\n".encode() * 64
                    started = time.perf_counter()
                    upload = await client.post(
                        "/api/v1/files/",
                        headers=headers,
                        files={"upload_file": ("new.txt", payload, "text/plain")},
                    )
                    assert upload.status_code == 200, upload.text
                    durations.append(time.perf_counter() - started)
                    uploaded.append((upload.json()["id"], payload))
                    round_number += 1
                    await asyncio.sleep(0.05)
            assert worker.returncode == 0, worker.stderr.read().decode()[-2000:]
        report["worker"] = json.loads((path / "worker.json").read_text())
        assert (
            report["worker"]["max_rss_bytes"]
            <= report["acceptance"]["maximum_worker_rss_bytes"]
        )
        _assert_adopted(url)
        assert _source_facts(url) == state["expected_sources"]

        _dump(postgres_container, test_settings.postgres_db, path / "after.dump")
        restore_started = time.perf_counter()
        _restore(postgres_container, path / "before.dump", "before_restore")
        _restore(postgres_container, path / "after.dump", "after_restore")
        before_url = url.rsplit("/", 1)[0] + "/before_restore"
        after_url = url.rsplit("/", 1)[0] + "/after_restore"
        assert _source_facts(before_url) == state["expected_sources"]
        assert _source_facts(after_url) == _source_facts(url)
        _assert_adopted(after_url)
        report["restore_seconds"] = time.perf_counter() - restore_started

        from eneo.object_content.runtime import object_content_runtime
        from eneo.server.dependencies.lifespan import startup

        await object_content_runtime.stop()
        await sessionmanager.close()
        set_settings(test_settings.model_copy(update={"postgres_db": "after_restore"}))
        restart_started = time.perf_counter()
        await startup()
        report["restored_application_startup_seconds"] = (
            time.perf_counter() - restart_started
        )
        async with db_container():
            icon = await client.get(f"/api/v1/icons/{state['icon_id']}/")
            assert icon.status_code == 200 and icon.content == b"icon bytes"
            for file_id, expected in state["files"][:4]:
                response = await _signed_download(
                    client, headers, UUID(file_id), original=False
                )
                assert response.status_code == 200 and response.content == expected
            for file_id, expected in uploaded:
                response = await _signed_download(
                    client, headers, UUID(file_id), original=True
                )
                assert response.status_code == 200 and response.content == expected
        ordered = sorted(durations)
        report["foreground_api"] = {
            "transport": "authenticated File and public Icon production routes through ASGI",
            "samples": len(ordered),
            "concurrency": 1,
            "p50_seconds": ordered[int((len(ordered) - 1) * 0.50)],
            "p95_seconds": ordered[int((len(ordered) - 1) * 0.95)],
            "p99_seconds": ordered[int((len(ordered) - 1) * 0.99)],
            "failed_requests": 0,
        }
        report["elapsed_seconds"] = time.perf_counter() - state["started"]
        stop, measurement = database_measurements
        stop.set()
        report["database"] = await asyncio.to_thread(measurement.result, timeout=15)
        report["backup_files_bytes"] = sum(
            item.stat().st_size for item in path.glob("*.dump")
        )
        assert (
            report["database"]["minimum_volume_free_bytes"]
            >= report["acceptance"]["minimum_database_volume_free_bytes"]
        )
        assert (
            report["elapsed_seconds"]
            < report["acceptance"]["maximum_rehearsal_seconds"]
        )
        output = os.getenv("ENEO_FILE_ICON_REHEARSAL_OUTPUT")
        if output:
            Path(output).write_text(json.dumps(report, indent=2) + "\n")
        backup_output = os.getenv("ENEO_FILE_ICON_REHEARSAL_BACKUP")
        if backup_output:
            # Preserve synthetic bridge state for the separate contraction image.
            # Exclusive creation prevents replacing an existing recovery artifact.
            with (
                Path(backup_output).open("xb") as destination,
                (path / "after.dump").open("rb") as source,
            ):
                shutil.copyfileobj(source, destination, length=_MIB)
    finally:
        for process in (killed, worker):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


async def _worker_main():
    database = DatabaseSessionManager()
    database.init(os.environ["ENEO_REHEARSAL_CHILD_DATABASE"])
    worker = FileIconBackfill(
        FileIconBackfillSettings(
            batch_rows=32, lease_seconds=int(os.environ["ENEO_REHEARSAL_CHILD_LEASE"])
        ),
        ObjectContentService(ObjectContentCoreSettings(_env_file=None), database),
        database,
    )
    started = time.perf_counter()
    runs = 0
    active_seconds = 0.0
    try:
        async with asyncio.timeout(240):
            while True:
                batch_started = time.perf_counter()
                result = await worker.run_once()
                active_seconds += time.perf_counter() - batch_started
                runs += 1
                if result.state is FileIconBackfillState.COMPLETE:
                    break
                assert result.state is FileIconBackfillState.ACTIVE, result
                await asyncio.sleep(0.05)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        Path(os.environ["ENEO_REHEARSAL_CHILD_OUTPUT"]).write_text(
            json.dumps(
                {
                    "runs": runs,
                    "elapsed_seconds": time.perf_counter() - started,
                    "active_seconds": active_seconds,
                    "schedule": "repeated run_once with 50 ms gaps; production minute cron not exercised",
                    "max_rss_bytes": int(
                        usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                    ),
                    "cpu_seconds": usage.ru_utime + usage.ru_stime,
                }
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(_worker_main())
