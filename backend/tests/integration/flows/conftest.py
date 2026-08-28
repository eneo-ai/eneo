from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TextIO
from uuid import uuid4

import pytest
import sqlalchemy as sa
from arq import create_pool
from arq.connections import ArqRedis
from arq.jobs import Job
from dependency_injector import providers
from httpx import AsyncClient
from testcontainers.community.redis import RedisContainer

from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.runtime.executor import (
    _PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV,
    _PROCESS_TEST_CRASH_EXIT_CODE,
)
from eneo.flows.runtime.platform_execution_backend import PlatformFlowExecutionBackend
from eneo.jobs.job_manager import JobManager
from eneo.jobs.job_serialization import deserialize_job, serialize_job
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.container.container import Container
from eneo.redis.connection import build_arq_redis_settings
from eneo.roles.permissions import Permission
from eneo.tasks.arq_adapter import ArqTaskEnqueuer
from eneo.tasks.routing import task_queue_routing
from tests.integration.conftest import (
    _IN_DEVCONTAINER,
    _TEST_NETWORK,
    _container_network_ip,
    _host_resolves,
)

_FLOW_TASK_TIMEOUT_SECONDS = 5
_WORKER_PARENT_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "TMPDIR",
    "TZ",
    "VIRTUAL_ENV",
)


@dataclass(frozen=True, slots=True)
class PublishedComposeTextFlow:
    flow_id: str
    step_id: str
    published_version: int


@dataclass(frozen=True, slots=True, repr=False)
class FlowProcessAuthHeaders(Mapping[str, str]):
    token: str

    def __getitem__(self, key: str) -> str:
        if key != "Authorization":
            raise KeyError(key)
        return f"Bearer {self.token}"

    def __iter__(self) -> Iterator[str]:
        return iter(("Authorization",))

    def __len__(self) -> int:
        return 1

    def __repr__(self) -> str:
        return "FlowProcessAuthHeaders(<redacted>)"


@dataclass(slots=True, repr=False)
class FlowBrokerWorkerSeam:
    broker_client: ArqRedis
    queue_name: str
    maintenance_queue_name: str
    worker_hostname: str
    worker_environment: dict[str, str]
    worker_log_path: Path
    task_timeout_seconds: int
    worker_process: subprocess.Popen[str] | None = None
    worker_log: TextIO | None = None

    async def discard_single_queued_delivery(self) -> None:
        pending_count = await self.broker_client.zcard(self.queue_name)
        if pending_count != 1:
            raise AssertionError(
                "Expected exactly one delivery on the disposable Flow queue, "
                f"found {pending_count}."
            )
        deleted_count = await self.broker_client.delete(self.queue_name)
        if deleted_count != 1:
            raise AssertionError("The disposable Flow queue delivery was not deleted.")

    async def start_worker(
        self, *, crash_after_attempt_start_run_id: str | None = None
    ) -> None:
        await self._start_worker_process(
            settings_path=(
                "eneo.worker.platform_tasks.PlatformExecutionWorkerSettings"
            ),
            readiness_queue=self.queue_name,
            crash_after_attempt_start_run_id=crash_after_attempt_start_run_id,
        )

    async def _start_worker_process(
        self,
        *,
        settings_path: str,
        readiness_queue: str,
        crash_after_attempt_start_run_id: str | None = None,
    ) -> None:
        if self.worker_process is not None:
            raise RuntimeError("Flow process-test worker is already running.")

        environment = dict(self.worker_environment)
        if crash_after_attempt_start_run_id is not None:
            environment[_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV] = (
                crash_after_attempt_start_run_id
            )
        else:
            environment.pop(_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV, None)

        await self.broker_client.delete(f"{readiness_queue}:health-check")
        self.worker_log = self.worker_log_path.open("w", encoding="utf-8")
        self.worker_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "arq",
                settings_path,
            ],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            stdout=self.worker_log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        await self._wait_until_worker_ready(
            queue_name=readiness_queue,
            timeout_seconds=30,
        )

    async def wait_for_task_result(
        self,
        *,
        task_id: str,
        timeout_seconds: float = 30,
        queue_name: str | None = None,
    ) -> dict[str, object]:
        result = Job(
            task_id,
            redis=self.broker_client,
            _queue_name=queue_name or self.queue_name,
        )
        try:
            value = await result.result(timeout=timeout_seconds, poll_delay=0.1)
        except Exception as exc:
            raise AssertionError(
                f"Platform task {task_id} did not complete successfully. "
                f"Worker log tail:\n{self.worker_log_tail()}"
            ) from exc
        if not isinstance(value, dict) or not all(
            isinstance(key, str) for key in value
        ):
            raise AssertionError(
                f"Platform task {task_id} returned a non-object result."
            )
        return dict(value)

    async def send_task_and_wait(
        self, *, task_name: str, timeout_seconds: float = 30
    ) -> dict[str, object]:
        queue_name = self.queue_name
        using_maintenance_worker = task_name != "flows.execute"
        if using_maintenance_worker:
            await self.close()
            queue_name = self.maintenance_queue_name
            await self._start_worker_process(
                settings_path=(
                    "eneo.worker.platform_tasks.PlatformMaintenanceWorkerSettings"
                ),
                readiness_queue=queue_name,
            )
        task_id = str(uuid4())
        result = await self.broker_client.enqueue_job(
            task_name,
            _job_id=task_id,
            _queue_name=queue_name,
        )
        if result is None:
            raise AssertionError(f"Platform runtime refused duplicate {task_name}.")
        task_result = await self.wait_for_task_result(
            task_id=task_id,
            timeout_seconds=timeout_seconds,
            queue_name=queue_name,
        )
        if using_maintenance_worker:
            await self.close()
            await self.start_worker()
        return task_result

    async def wait_for_public_run_status(
        self,
        *,
        client: AsyncClient,
        headers: Mapping[str, str],
        flow_id: str,
        run_id: str,
        expected_status: str,
        timeout_seconds: float,
    ) -> tuple[dict[str, object], list[str]]:
        deadline = monotonic() + timeout_seconds
        observed_statuses: list[str] = []
        last_payload: dict[str, object] | None = None
        while monotonic() < deadline:
            if self.worker_process is not None:
                self.assert_worker_alive()
            response = await client.get(
                f"/api/v1/flows/{flow_id}/runs/{run_id}/",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            if not isinstance(payload, dict):
                raise AssertionError("Public Flow run response was not an object.")
            status = payload.get("status")
            if not isinstance(status, str):
                raise AssertionError("Public Flow run response omitted status.")
            last_payload = dict(payload)
            if not observed_statuses or observed_statuses[-1] != status:
                observed_statuses.append(status)
            if status == expected_status:
                return last_payload, observed_statuses
            if status in {"cancelled", "completed", "failed"}:
                raise AssertionError(
                    f"Flow run reached {status!r} while waiting for "
                    f"{expected_status!r}: {last_payload}"
                )
            await asyncio.sleep(0.1)
        raise AssertionError(
            f"Flow run did not reach {expected_status!r} within {timeout_seconds}s. "
            f"Observed statuses: {observed_statuses}; last payload: {last_payload}; "
            f"worker log tail:\n{self.worker_log_tail()}"
        )

    async def wait_for_worker_child_exit(self, *, timeout_seconds: float = 30) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            process = self.worker_process
            if process is None:
                raise AssertionError("Flow process-test worker has not been started.")
            exit_code = process.poll()
            if exit_code == _PROCESS_TEST_CRASH_EXIT_CODE:
                await asyncio.to_thread(process.wait)
                if self.worker_log is not None:
                    self.worker_log.close()
                self.worker_process = None
                self.worker_log = None
                return
            if exit_code is not None:
                raise AssertionError(
                    f"Disposable Flow worker exited with unexpected code {exit_code}."
                )
            await asyncio.sleep(0.1)
        raise AssertionError(
            "The disposable platform worker did not hard-exit as expected. "
            f"Worker log tail:\n{self.worker_log_tail()}"
        )

    def assert_worker_alive(self) -> None:
        process = self.worker_process
        if process is None:
            raise AssertionError("Flow process-test worker has not been started.")
        exit_code = process.poll()
        if exit_code is not None:
            raise AssertionError(
                f"Disposable Flow worker exited early with code {exit_code}. "
                f"Worker log tail:\n{self.worker_log_tail()}"
            )

    def worker_log_tail(self, *, line_count: int = 40) -> str:
        if not self.worker_log_path.exists():
            return "<worker log not created>"
        lines = self.worker_log_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        return "\n".join(lines[-line_count:])

    async def close(self) -> None:
        try:
            process = self.worker_process
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.to_thread(process.wait, 10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await asyncio.to_thread(process.wait, 10)
            elif process is not None:
                await asyncio.to_thread(process.wait)
        finally:
            if self.worker_log is not None:
                self.worker_log.close()
            self.worker_process = None
            self.worker_log = None

    async def _wait_until_worker_ready(
        self, *, queue_name: str, timeout_seconds: float
    ) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            self.assert_worker_alive()
            if await self.broker_client.exists(f"{queue_name}:health-check"):
                return
            await asyncio.sleep(0.1)
        raise AssertionError(
            "Disposable Flow worker did not report its exact owned queue within "
            f"{timeout_seconds}s. Worker log tail:\n{self.worker_log_tail()}"
        )


@pytest.fixture
async def flow_process_auth_headers(
    db_container,
    patch_auth_service_jwt,
    admin_user,
) -> FlowProcessAuthHeaders:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        session = container.session()
        user_repo = container.user_repo()
        auth_service = container.auth_service()
        role = Roles(
            name=f"Flow process proof {uuid4().hex[:8]}",
            permissions=[
                Permission.FLOWS_MANAGE.value,
                Permission.FLOWS_RUN.value,
                Permission.FLOWS_TRACE.value,
            ],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(
                user_id=admin_user.id,
                role_id=role.id,
            )
        )
        await session.flush()
        user = await user_repo.get_user_by_email(admin_user.email)
        token = auth_service.create_access_token_for_user(user)
    return FlowProcessAuthHeaders(token=token)


@pytest.fixture
def create_published_compose_text_flow() -> Callable[
    [AsyncClient, Mapping[str, str]], Awaitable[PublishedComposeTextFlow]
]:
    async def _create(
        client: AsyncClient,
        headers: Mapping[str, str],
    ) -> PublishedComposeTextFlow:
        suffix = uuid4().hex[:8]
        space_response = await client.post(
            "/api/v1/spaces/",
            json={"name": f"flow-process-proof-{suffix}"},
            headers=headers,
        )
        assert space_response.status_code == 201, space_response.text
        space_id = space_response.json()["id"]

        flow_response = await client.post(
            "/api/v1/flows/",
            json={
                "space_id": space_id,
                "name": f"Flow process proof {suffix}",
                "description": "Deterministic broker and worker process proof.",
                "steps": [],
            },
            headers=headers,
        )
        assert flow_response.status_code == 201, flow_response.text
        flow_id = flow_response.json()["id"]

        assistant_response = await client.post(
            f"/api/v1/flows/{flow_id}/assistants/",
            json={"name": f"Flow process proof assistant {suffix}"},
            headers=headers,
        )
        assert assistant_response.status_code == 201, assistant_response.text
        assistant_id = assistant_response.json()["id"]

        update_response = await client.patch(
            f"/api/v1/flows/{flow_id}/",
            json={
                "name": f"Flow process proof {suffix}",
                "description": "Deterministic broker and worker process proof.",
                "steps": [
                    {
                        "assistant_id": assistant_id,
                        "step_order": 1,
                        "user_description": "Return the submitted text unchanged.",
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_mode": "compose_text",
                        "output_type": "text",
                    }
                ],
            },
            headers=headers,
        )
        assert update_response.status_code == 200, update_response.text
        updated_flow = update_response.json()
        step_id = updated_flow["steps"][0]["id"]

        publish_response = await client.post(
            f"/api/v1/flows/{flow_id}/publish/",
            headers=headers,
        )
        assert publish_response.status_code == 200, publish_response.text
        published_version = publish_response.json()["published_version"]

        assert isinstance(flow_id, str)
        assert isinstance(step_id, str)
        assert isinstance(published_version, int)
        return PublishedComposeTextFlow(
            flow_id=flow_id,
            step_id=step_id,
            published_version=published_version,
        )

    return _create


@pytest.fixture
async def flow_broker_worker_seam(
    setup_database,
    test_settings: Settings,
    tmp_path: Path,
) -> AsyncIterator[FlowBrokerWorkerSeam]:
    _ = setup_database
    redis = RedisContainer(image="redis:7-alpine")
    if _TEST_NETWORK:
        redis = redis.with_kwargs(network=_TEST_NETWORK)
    async with AsyncExitStack() as cleanup:
        await asyncio.to_thread(redis.start)
        cleanup.push_async_callback(asyncio.to_thread, redis.stop)
        redis_host, redis_port = _disposable_redis_endpoint(redis)
        identity = uuid4().hex
        queue_name = f"flows.wi04b.{identity}"
        runtime_settings = test_settings.model_copy(
            update={
                "redis_host": redis_host,
                "redis_port": redis_port,
                "redis_db": 0,
                "task_execution_queue": queue_name,
                "task_maintenance_queue": f"{queue_name}:maintenance",
                "task_execution_max_jobs": 1,
                "task_execution_timeout_seconds": _FLOW_TASK_TIMEOUT_SECONDS,
            }
        )
        original_settings = get_settings()
        set_settings(runtime_settings)
        try:
            job_manager = JobManager()
            await job_manager.init()
        finally:
            set_settings(original_settings)
        cleanup.push_async_callback(job_manager.close)

        execution_backend = PlatformFlowExecutionBackend(
            task_enqueuer=ArqTaskEnqueuer(
                job_manager=job_manager,
                routing=task_queue_routing(runtime_settings),
            )
        )
        Container.flow_execution_backend.override(providers.Object(execution_backend))
        cleanup.callback(Container.flow_execution_backend.reset_last_overriding)
        broker_client = await create_pool(
            build_arq_redis_settings(runtime_settings),
            job_serializer=serialize_job,
            job_deserializer=deserialize_job,
        )
        cleanup.push_async_callback(broker_client.aclose)
        seam = FlowBrokerWorkerSeam(
            broker_client=broker_client,
            queue_name=queue_name,
            maintenance_queue_name=f"{queue_name}:maintenance",
            worker_hostname=f"flow-wi04b-{identity}@%h",
            worker_environment=_flow_worker_environment(
                settings=runtime_settings,
                queue_name=queue_name,
            ),
            worker_log_path=tmp_path / "flow-worker.log",
            task_timeout_seconds=_FLOW_TASK_TIMEOUT_SECONDS,
        )
        cleanup.push_async_callback(seam.close)
        yield seam


def _disposable_redis_endpoint(redis: RedisContainer) -> tuple[str, int]:
    if not _IN_DEVCONTAINER:
        return redis.get_container_host_ip(), int(redis.get_exposed_port(6379))

    wrapped_container = redis.get_wrapped_container()
    container_name = wrapped_container.name
    if _host_resolves(container_name):
        return container_name, 6379
    network_ip = _container_network_ip(wrapped_container, _TEST_NETWORK)
    if network_ip:
        return network_ip, 6379
    raise RuntimeError("Disposable Flow Redis container is unreachable.")


def _flow_worker_environment(*, settings: Settings, queue_name: str) -> dict[str, str]:
    environment = {
        key: value
        for key in _WORKER_PARENT_ENV_ALLOWLIST
        if (value := os.environ.get(key)) is not None
    }
    environment.update(
        {
            "POSTGRES_USER": settings.postgres_user,
            "POSTGRES_HOST": settings.postgres_host,
            "POSTGRES_PASSWORD": settings.postgres_password,
            "POSTGRES_PORT": str(settings.postgres_port),
            "POSTGRES_DB": settings.postgres_db,
            "REDIS_HOST": settings.redis_host,
            "REDIS_PORT": str(settings.redis_port),
            "REDIS_DB": str(settings.redis_db),
            "TASK_EXECUTION_QUEUE": queue_name,
            "TASK_MAINTENANCE_QUEUE": f"{queue_name}:maintenance",
            "TASK_EXECUTION_MAX_JOBS": "1",
            "TASK_EXECUTION_TIMEOUT_SECONDS": str(_FLOW_TASK_TIMEOUT_SECONDS),
            "FLOW_MAX_INLINE_TEXT_BYTES": str(settings.flow_max_inline_text_bytes),
            "FLOW_LLM_REQUEST_TIMEOUT_SECONDS": str(
                settings.flow_llm_request_timeout_seconds
            ),
            "FLOW_RUNTIME_STEP_TIMEOUT_HARD_CEILING_SECONDS": str(
                settings.flow_runtime_step_timeout_hard_ceiling_seconds
            ),
            "API_PREFIX": settings.api_prefix,
            "API_KEY_LENGTH": str(settings.api_key_length),
            "API_KEY_HEADER_NAME": settings.api_key_header_name,
            "JWT_AUDIENCE": settings.jwt_audience,
            "JWT_ISSUER": settings.jwt_issuer,
            "JWT_EXPIRY_TIME": str(settings.jwt_expiry_time),
            "JWT_ALGORITHM": settings.jwt_algorithm,
            "JWT_SECRET": settings.jwt_secret,
            "JWT_TOKEN_PREFIX": settings.jwt_token_prefix,
            "URL_SIGNING_KEY": settings.url_signing_key,
            "ENCRYPTION_KEY": settings.encryption_key or "",
            "OPENAPI_ONLY_MODE": "false",
            "TENANT_CREDENTIALS_ENABLED": "false",
            "TESTING": "true",
            "DEV": "true",
        }
    )
    return environment
