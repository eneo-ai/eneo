from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import TextIO
from uuid import uuid4

import pytest
import sqlalchemy as sa
from celery import Celery
from dependency_injector import providers
from httpx import AsyncClient
from redis.asyncio import Redis as AsyncRedis
from testcontainers.redis import RedisContainer

from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.runtime.celery_app import create_flow_celery_app
from eneo.flows.runtime.celery_execution_backend import CeleryFlowExecutionBackend
from eneo.flows.runtime.executor import (
    _PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV,
    _PROCESS_TEST_CRASH_EXIT_CODE,
)
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from tests.integration.conftest import (
    _IN_DEVCONTAINER,
    _TEST_NETWORK,
    _container_network_ip,
    _host_resolves,
)

_FLOW_TASK_TIMEOUT_SECONDS = 5
_FLOW_VISIBILITY_TIMEOUT_SECONDS = 90
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
    celery_app: Celery
    broker_client: AsyncRedis
    queue_name: str
    worker_hostname: str
    worker_environment: dict[str, str]
    worker_log_path: Path
    task_timeout_seconds: int
    worker_process: subprocess.Popen[str] | None = None
    worker_log: TextIO | None = None

    async def discard_single_queued_delivery(self) -> None:
        pending_count = await self.broker_client.llen(self.queue_name)
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
        if self.worker_process is not None:
            raise RuntimeError("Flow process-test worker is already running.")

        environment = dict(self.worker_environment)
        if crash_after_attempt_start_run_id is not None:
            environment[_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV] = (
                crash_after_attempt_start_run_id
            )
        else:
            environment.pop(_PROCESS_TEST_CRASH_AFTER_ATTEMPT_START_RUN_ID_ENV, None)

        self.worker_log = self.worker_log_path.open("w", encoding="utf-8")
        self.worker_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "eneo.flows.runtime.celery_app:celery_app",
                "worker",
                "--loglevel=INFO",
                "--pool=prefork",
                "--concurrency=1",
                "--queues",
                self.queue_name,
                "--hostname",
                self.worker_hostname,
                "--without-gossip",
                "--without-mingle",
            ],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            stdout=self.worker_log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        await self._wait_until_worker_ready(timeout_seconds=30)

    async def wait_for_task_result(
        self, *, task_id: str, timeout_seconds: float = 30
    ) -> dict[str, object]:
        result = self.celery_app.AsyncResult(task_id)
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            self.assert_worker_alive()
            if await asyncio.to_thread(result.ready):
                value = await asyncio.to_thread(
                    result.get,
                    timeout=1,
                    propagate=True,
                )
                if not isinstance(value, dict) or not all(
                    isinstance(key, str) for key in value
                ):
                    raise AssertionError(
                        f"Celery task {task_id} returned a non-object result."
                    )
                return dict(value)
            await asyncio.sleep(0.1)
        raise AssertionError(
            f"Celery task {task_id} did not finish within {timeout_seconds}s. "
            f"Worker log tail:\n{self.worker_log_tail()}"
        )

    async def send_task_and_wait(
        self, *, task_name: str, timeout_seconds: float = 30
    ) -> dict[str, object]:
        result = await asyncio.to_thread(
            partial(
                self.celery_app.send_task,
                task_name,
                queue=self.queue_name,
            )
        )
        task_id = getattr(result, "id", None)
        if not isinstance(task_id, str):
            raise AssertionError(f"Celery did not assign an id to {task_name}.")
        return await self.wait_for_task_result(
            task_id=task_id,
            timeout_seconds=timeout_seconds,
        )

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
        exit_markers = (
            f"exitcode {_PROCESS_TEST_CRASH_EXIT_CODE}",
            f"exitcode={_PROCESS_TEST_CRASH_EXIT_CODE}",
            f"exit code {_PROCESS_TEST_CRASH_EXIT_CODE}",
        )
        while monotonic() < deadline:
            self.assert_worker_alive()
            log_text = self.worker_log_path.read_text(
                encoding="utf-8", errors="replace"
            )
            if any(marker in log_text for marker in exit_markers):
                return
            await asyncio.sleep(0.1)
        raise AssertionError(
            "The disposable worker did not report the expected hard-exited pool "
            f"child. Worker log tail:\n{self.worker_log_tail()}"
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

    async def _wait_until_worker_ready(self, *, timeout_seconds: float) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            self.assert_worker_alive()
            active_queues = await asyncio.to_thread(
                self.celery_app.control.inspect(timeout=0.5).active_queues
            )
            if active_queues and {
                queue["name"] for queues in active_queues.values() for queue in queues
            } == {self.queue_name}:
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
                "redis_db_celery_broker": 1,
                "redis_db_celery_result": 2,
                "redis_db_auth_broker": 3,
                "flow_celery_queue": queue_name,
                "flow_celery_maintenance_queue": queue_name,
                "flow_celery_worker_queues": queue_name,
                "flow_task_timeout_seconds": _FLOW_TASK_TIMEOUT_SECONDS,
                "celery_visibility_timeout_seconds": (_FLOW_VISIBILITY_TIMEOUT_SECONDS),
            }
        )
        original_settings = get_settings()
        set_settings(runtime_settings)
        try:
            celery_app = create_flow_celery_app()
        finally:
            set_settings(original_settings)
        cleanup.callback(celery_app.close)

        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True
        assert celery_app.conf.worker_prefetch_multiplier == 1
        assert (
            celery_app.conf.broker_transport_options["visibility_timeout"]
            == _FLOW_VISIBILITY_TIMEOUT_SECONDS
        )

        execution_backend = CeleryFlowExecutionBackend(
            celery_app=celery_app,
            queue_name=queue_name,
        )
        Container.flow_execution_backend.override(providers.Object(execution_backend))
        cleanup.callback(Container.flow_execution_backend.reset_last_overriding)
        broker_client = AsyncRedis(
            host=redis_host,
            port=redis_port,
            db=runtime_settings.redis_db_celery_broker,
            socket_timeout=runtime_settings.redis_conn_timeout,
            socket_connect_timeout=runtime_settings.redis_conn_timeout,
        )
        cleanup.push_async_callback(broker_client.aclose)
        seam = FlowBrokerWorkerSeam(
            celery_app=celery_app,
            broker_client=broker_client,
            queue_name=queue_name,
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
            "REDIS_DB_CELERY_BROKER": str(settings.redis_db_celery_broker),
            "REDIS_DB_CELERY_RESULT": str(settings.redis_db_celery_result),
            "REDIS_DB_AUTH_BROKER": str(settings.redis_db_auth_broker),
            "FLOW_CELERY_QUEUE": queue_name,
            "FLOW_CELERY_MAINTENANCE_QUEUE": queue_name,
            "FLOW_CELERY_WORKER_QUEUES": queue_name,
            "FLOW_TASK_TIMEOUT_SECONDS": str(_FLOW_TASK_TIMEOUT_SECONDS),
            "CELERY_VISIBILITY_TIMEOUT_SECONDS": str(_FLOW_VISIBILITY_TIMEOUT_SECONDS),
            "FLOW_MAX_INLINE_TEXT_BYTES": str(settings.flow_max_inline_text_bytes),
            "FLOW_LLM_REQUEST_TIMEOUT_SECONDS": str(
                settings.flow_llm_request_timeout_seconds
            ),
            "FLOW_RUNTIME_STEP_TIMEOUT_HARD_CEILING_SECONDS": str(
                settings.flow_runtime_step_timeout_hard_ceiling_seconds
            ),
            "UPLOAD_FILE_TO_SESSION_MAX_SIZE": str(
                settings.upload_file_to_session_max_size
            ),
            "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE": str(
                settings.upload_image_to_session_max_size
            ),
            "UPLOAD_MAX_FILE_SIZE": str(settings.upload_max_file_size),
            "TRANSCRIPTION_MAX_FILE_SIZE": str(settings.transcription_max_file_size),
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
