"""The executor's session holds no transaction while a step waits on outside
work, unless the step has written in it.

An audio step is run on a real session with stubs that stop at each wait: the
audio download being spooled, a transcription request and a completion
request. While a stub is stopped the test looks at the database: no backend
whose transaction began before the wait may still be idle in it or hold a
relation lock, and `flow_runs` can take a schema lock within a second. A step
that reads its audio files one source at a time also stops at its second
mapped completion call, and its later sources wait in the transaction that
wrote the first source's transcript.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.exc import DBAPIError

from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import FlowRuns, FlowRunStepInputFiles
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_protocol import PendingFileContent, PreparedFileUpload
from eneo.files.text import TEXT_EXTRACTION_WARNINGS
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    flow_run_execution_owner,
)
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.container.container import Container
from eneo.model_providers.domain.provider_call_observer import (
    CompletionCallResultFacts,
    TranscriptionCallRequestFacts,
    TranscriptionCallResultFacts,
    build_provider_call_request_facts,
)
from tests.integration.flows.test_flow_step_file_mapping_contract import (
    _bind_runtime_uploaded_files,  # pyright: ignore[reportPrivateUsage]
    _create_running_step_file_flow,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.test_flow_transcription import (
    _SPEAKER_CHOICE,  # pyright: ignore[reportPrivateUsage]
    _SpaceStub,  # pyright: ignore[reportPrivateUsage]
    _state,  # pyright: ignore[reportPrivateUsage]
    _transcribers,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,  # pyright: ignore[reportPrivateUsage]
    _mock_assistant_for_execute_step,  # pyright: ignore[reportPrivateUsage]
    _runtime_step,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_AUDIO = b"audio supplied to the transcription provider"
# How long each wait is held after the test has noted when it began.
_HOLD_SECONDS = 0.2
_LOCK_TIMEOUT = "1s"
_DOCUMENTS_CONTRACT: dict[str, object] = {
    "type": "object",
    "required": ["documents"],
    "additionalProperties": False,
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_label",
                    "source_file_id",
                    "extraction_warnings",
                    "title",
                ],
                "properties": {
                    "source_label": {"type": "string"},
                    "source_file_id": {"type": "string"},
                    "title": {"type": "string"},
                    "extraction_warnings": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": sorted(TEXT_EXTRACTION_WARNINGS),
                        },
                    },
                },
            },
        }
    },
}


class _Waits:
    """Each wait a stub reaches, held until the test has looked at it."""

    def __init__(self) -> None:
        self.reached: asyncio.Queue[tuple[str, asyncio.Event]] = asyncio.Queue()

    async def hold(self, phase: str) -> None:
        released = asyncio.Event()
        await self.reached.put((phase, released))
        await released.wait()


@dataclass(frozen=True)
class _Held:
    phase: str
    idle_in_transaction: int
    relation_locks: int
    flow_runs_alterable: bool


@dataclass(frozen=True)
class _Case:
    executor: Any
    run: Any
    step: Any
    metadata: dict[str, object]
    waits: _Waits
    sources: int


async def _audio_stream() -> AsyncIterator[bytes]:
    yield _AUDIO


def _held_download(download: Any, waits: _Waits) -> Any:
    """The download as a stream the spool reads, stopped before its bytes."""

    async def chunks() -> AsyncIterator[bytes]:
        await waits.hold("audio spool")
        yield _AUDIO

    return replace(download, chunks=chunks(), verified_path=None)


def _transcriber(waits: _Waits) -> Any:
    async def transcribe(audio_file: Any, model: Any, *, observer: Any, **_: Any):
        call_id = await observer.started(
            TranscriptionCallRequestFacts(
                request_schema_version=2,
                provider_request_hash=uuid4().hex * 2,
                requested_model="whisper-1",
                provider="openai",
                audio_seconds=12.0,
            )
        )
        await waits.hold("transcription")
        await observer.completed(
            call_id,
            TranscriptionCallResultFacts(
                response_model="whisper-1", provider_response_id=None
            ),
        )
        return TranscribedAudio(text="Mötet började.", duration_seconds=12.0)

    return SimpleNamespace(transcribe=transcribe)


def _assistant(waits: _Waits, *, completion_model_id: UUID, answers: list[str]):
    assistant = _mock_assistant_for_execute_step()
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model.id = completion_model_id
    remaining = iter(answers)

    async def get_response(
        *,
        question: str,
        provider_call_observer: Any,
        provider_call_reason: Any = "initial",
        **_: Any,
    ):
        call_id = await provider_call_observer.started(
            build_provider_call_request_facts(
                requested_model="test",
                provider="test",
                messages=[{"role": "user", "content": question}],
                request_kwargs={},
                reason=provider_call_reason,
            )
        )
        await waits.hold("completion")
        await provider_call_observer.completed(
            call_id,
            CompletionCallResultFacts(
                response_model="test",
                provider_response_id=f"resp-{uuid4()}",
                num_tokens_input=3,
                num_tokens_output=1,
            ),
        )
        return SimpleNamespace(completion=next(remaining), total_token_count=4)

    assistant.get_response = AsyncMock(side_effect=get_response)
    return assistant


async def _seed_audio(*, container: Any, admin_user: Any, name: str) -> UUID:
    audio = await container.file_service(user=admin_user).save_prepared_file(
        PreparedFileUpload(
            name=name,
            file_type=FileType.AUDIO,
            display_media_type="audio/wav",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_audio_stream(),
                    declared_media_type="audio/wav",
                    verified_media_type="audio/wav",
                ),
            ),
        )
    )
    return audio.id


@pytest.fixture(params=["one_call", "per_source"])
async def held_audio_step(
    request: Any,
    db_container: Any,
    object_content_runtime_ready: Any,
    admin_user: Any,
    test_tenant: Any,
    completion_model_factory: Any,
    space_factory: Any,
    assistant_factory: Any,
) -> AsyncIterator[_Case]:
    per_source = request.param == "per_source"
    async with db_container(user=admin_user) as container:
        session = container.session()
        flow, source, run, _ = await _create_running_step_file_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        file_ids = [
            await _seed_audio(container=container, admin_user=admin_user, name=name)
            for name in (
                ("first.wav", "second.wav") if per_source else ("meeting.wav",)
            )
        ]
        await _bind_runtime_uploaded_files(
            session=session,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            uploaded_for_step_id=source.id,
            file_ids=file_ids,
        )
        session.add_all(
            [
                FlowRunStepInputFiles(
                    flow_run_id=run.id,
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    step_id=source.id,
                    step_order=source.step_order,
                    attempt_no=1,
                    file_id=file_id,
                    ordinal=ordinal,
                )
                for ordinal, file_id in enumerate(file_ids)
            ]
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(execution_heartbeat_at=datetime.now(timezone.utc))
        )
        completion_model_id = await session.scalar(
            sa.select(Assistants.completion_model_id).where(
                Assistants.id == source.assistant_id
            )
        )
        assert completion_model_id is not None

    waits = _Waits()
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        executor, _, _, _ = _build_executor(admin_user, max_inline_text_bytes=2048)
        executor.session = session
        executor.flow_run_repo = container.flow_run_repo()
        executor.file_service = container.file_service(user=admin_user)
        executor.file_repo = container.file_repo()
        executor.flow_run_terminalizer = container.flow_run_terminalizer()
        open_download = executor.file_service.get_audio_download

        async def get_audio_download(file_id: UUID) -> Any:
            return _held_download(await open_download(file_id), waits)

        executor.file_service.get_audio_download = get_audio_download

        async def retrieve_passages(**_: Any) -> tuple[list[Any], None, list[Any]]:
            # A knowledge-backed step reads its passages on the executor's
            # session after the attempt is activated, right before each call.
            await session.scalar(
                sa.select(Assistants.id).where(Assistants.id == source.assistant_id)
            )
            return [], None, []

        executor._retrieve_rag_chunks = retrieve_passages  # pyright: ignore[reportPrivateUsage]
        model = SimpleNamespace(
            id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
        )
        executor.space_repo.one.return_value = _SpaceStub([model], model)
        executor.transcribers = _transcribers(_transcriber(waits))
        executor._load_assistant = AsyncMock(  # pyright: ignore[reportPrivateUsage]
            return_value=_assistant(
                waits,
                completion_model_id=completion_model_id,
                answers=(
                    [
                        '{"documents":[{"title":"First"}]}',
                        '{"documents":[{"title":"Second"}]}',
                    ]
                    if per_source
                    else ["Meeting notes."]
                ),
            )
        )
        step = replace(
            _runtime_step(
                input_type="file",
                output_type="json",
                output_contract=_DOCUMENTS_CONTRACT,
                input_config={
                    "runtime_input": {
                        "enabled": True,
                        "input_format": "audio",
                        "execution_mode": "per_source",
                        "max_files": 2,
                    }
                },
            )
            if per_source
            else _runtime_step(
                input_type="audio",
                input_bindings={"question": "Meeting notes\n{{step_input.text}}"},
            ),
            step_id=source.id,
            step_order=source.step_order,
            assistant_id=source.assistant_id,
        )
        # Read on the executor's session, as the executor reads the run before
        # its step: the transaction that read opens is what a wait must not hold.
        run = await executor.flow_run_repo.get(run_id=run.id, tenant_id=run.tenant_id)
        owner_token = flow_run_execution_owner.set(
            FlowRunExecutionOwner(
                run_id=run.id, tenant_id=run.tenant_id, revision=run.revision
            )
        )
        try:
            yield _Case(
                executor=executor,
                run=run,
                step=step,
                metadata={
                    "wizard": {
                        "transcription_enabled": True,
                        "transcription_model": {"id": str(model.id)},
                        "transcription_speaker_service": _SPEAKER_CHOICE,
                    }
                },
                waits=waits,
                sources=len(file_ids),
            )
        finally:
            flow_run_execution_owner.reset(owner_token)


async def _database_now() -> datetime:
    async with sessionmanager.session() as probe, probe.begin():
        now = await probe.scalar(sa.text("SELECT clock_timestamp()"))
    assert isinstance(now, datetime)
    return now


async def _transactions_held_since(since: datetime) -> tuple[int, int]:
    """Backends idle in a transaction opened before `since`, and the relation
    locks transactions opened before it still hold."""
    async with sessionmanager.session() as probe, probe.begin():
        idle = await probe.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
                " AND state = 'idle in transaction' AND xact_start < :since"
            ),
            {"since": since},
        )
        locks = await probe.scalar(
            sa.text(
                "SELECT count(*) FROM pg_locks AS lock"
                " JOIN pg_stat_activity AS activity ON activity.pid = lock.pid"
                " WHERE lock.locktype = 'relation'"
                " AND activity.datname = current_database()"
                " AND lock.pid <> pg_backend_pid() AND activity.xact_start < :since"
            ),
            {"since": since},
        )
    return int(idle or 0), int(locks or 0)


async def _flow_runs_alterable() -> bool:
    async with sessionmanager.session() as probe:
        transaction = await probe.begin()
        try:
            await probe.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
            await probe.execute(
                sa.text("ALTER TABLE flow_runs ADD COLUMN lock_probe integer")
            )
            return True
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig, "pgcode", None
            )
            if sqlstate == "55P03":  # lock_not_available
                return False
            raise
        finally:
            await transaction.rollback()


async def _what_the_wait_holds(phase: str) -> _Held:
    since = await _database_now()
    await asyncio.sleep(_HOLD_SECONDS)
    idle, locks = await _transactions_held_since(since)
    return _Held(
        phase=phase,
        idle_in_transaction=idle,
        relation_locks=locks,
        flow_runs_alterable=await _flow_runs_alterable(),
    )


async def _run_holding_each_wait(case: _Case) -> list[_Held]:
    execution = asyncio.create_task(
        case.executor._execute_step(  # pyright: ignore[reportPrivateUsage]
            step=case.step,
            run=case.run,
            state=_state(),
            attempt_no=1,
            version_metadata=case.metadata,
        )
    )
    held: list[_Held] = []
    try:
        while True:
            reached = asyncio.create_task(case.waits.reached.get())
            done, _ = await asyncio.wait(
                {reached, execution}, timeout=60, return_when=asyncio.FIRST_COMPLETED
            )
            if reached not in done:
                reached.cancel()
                assert done, "The step neither reached a wait nor finished."
                break
            phase, released = reached.result()
            held.append(await _what_the_wait_holds(phase))
            released.set()
        await execution
    finally:
        if not execution.done():
            execution.cancel()
    return held


async def test_a_wait_holds_a_transaction_only_once_the_step_wrote(
    held_audio_step: _Case,
):
    held = await _run_holding_each_wait(held_audio_step)

    # Every source is transcribed before the first completion call is sent.
    sources = held_audio_step.sources
    assert [wait.phase for wait in held] == (
        ["audio spool", "transcription"] * sources + ["completion"] * sources
    )
    # A transaction that has only read is ended before each wait. Source one's
    # inline transcript is written on the locked run row and stays uncommitted
    # until the attempt is activated, so every later source is downloaded and
    # transcribed in that transaction: the exposure that remains until inline
    # transcripts are written at activation.
    wrote = range(2, 2 * sources)
    assert [
        (
            wait.phase,
            wait.idle_in_transaction,
            wait.relation_locks > 0,
            wait.flow_runs_alterable,
        )
        for wait in held
    ] == [
        (wait.phase, 1, True, False) if index in wrote else (wait.phase, 0, False, True)
        for index, wait in enumerate(held)
    ]
