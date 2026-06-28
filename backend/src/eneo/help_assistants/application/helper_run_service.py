"""Application service for executing a single Help-Assistant run.

The service owns the orchestration of one helper-run: it authorizes the
caller against the *target* resource (the assistant whose prompt the user
wants help with), resolves the helper assistant from the active role
assignment, stamps the run, then drives the completion call.

Key invariants pinned here:

* **Tool / knowledge isolation (PRD §6.5).** The completion request is
  built from the *helper* assistant's prompt, model, collections, websites,
  integration_knowledge_list, and MCP servers. Nothing leaks from the
  ``target_assistant`` — silent inheritance is the failure mode this
  design rules out.
* **No extended logging (PRD §6 + Critical test #3).** ``extended_logging``
  is hard-coded to ``False`` on every call to ``completion_service``,
  regardless of the helper assistant's stored ``logging_enabled`` /
  ``insight_enabled``. The Question row is persisted with
  ``logging_details=None`` so ``questions_repo.add`` never inserts into
  the ``logging`` table.
* **Helper sessions stay hidden.** Each run writes a row in
  ``help_assistant_runs`` keyed on the new ``sessions.id``; the central
  ``_exclude_helper_run_sessions`` filter (step 013) keeps that session
  out of every session / conversation / insights endpoint.

The service does not touch the existing ``assistant_service.ask()`` path
— the guard in ``assistant_service.ask()`` rejecting helper assistants
lives in step 020.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncGenerator, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
    TokenUsage,
)
from eneo.assistants.assistant import Assistant
from eneo.assistants.references import ReferencesService
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run import HelperRun
from eneo.help_assistants.domain.helper_run_status import HelperRunStatus
from eneo.help_assistants.infrastructure.helper_run_repo import HelperRunRepo
from eneo.info_blobs.info_blob import (
    InfoBlobChunkInDBWithScore,
    InfoBlobInDBWithScore,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.main.models import ResourcePermission
from eneo.questions.question import QuestionAdd
from eneo.questions.questions_repo import QuestionRepository
from eneo.sessions.session import SessionAdd, SessionInDB
from eneo.sessions.sessions_repo import SessionRepository
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.assistants.assistant_service import AssistantService
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.help_assistants.application.org_space_assistant_role_service import (
        OrgSpaceAssistantRoleService,
    )


logger = get_logger(__name__)


_SUPPORTED_TARGET_TYPES = frozenset({"assistant"})


class HelperRunResponse(BaseModel):
    """Result of one ``HelperRunService.run`` call.

    Carries enough context for the router (step 022) to render a non-stream
    JSON body or stream Server-Sent Events back to the client. ``answer``
    is either the final string (non-stream) or an async generator that
    yields ``Completion`` chunks (stream).
    """

    run: HelperRun
    session: SessionInDB
    answer: str | AsyncGenerator[Completion, None]
    info_blobs: list[InfoBlobInDBWithScore]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class HelperRunService:
    def __init__(
        self,
        user: UserInDB,
        helper_run_repo: HelperRunRepo,
        role_service: "OrgSpaceAssistantRoleService",
        assistant_service: "AssistantService",
        session_repo: SessionRepository,
        question_repo: QuestionRepository,
        completion_service: "CompletionService",
        references_service: ReferencesService,
        factory: HelperAssistantsFactory,
        audit_service: "AuditService",
    ) -> None:
        self.user = user
        self.helper_run_repo = helper_run_repo
        self.role_service = role_service
        self.assistant_service = assistant_service
        self.session_repo = session_repo
        self.question_repo = question_repo
        self.completion_service = completion_service
        self.references_service = references_service
        self.factory = factory
        self.audit_service = audit_service

    async def run(
        self,
        *,
        kind: HelperKind,
        target_type: str,
        target_id: UUID,
        question: str,
        stream: bool = False,
    ) -> HelperRunResponse:
        """Start a helper run for ``target_id`` on behalf of the calling user.

        Concurrency: helper runs are not separately rate-limited — they flow
        through the same ``completion_service`` as ordinary assistant chats and
        are therefore bound by the same per-tenant model quota / provider rate
        limits. A dedicated per-user in-flight cap can be added later if
        helper-run abuse is observed in practice.
        """
        if target_type not in _SUPPORTED_TARGET_TYPES:
            raise BadRequestException(
                f"Unsupported helper-run target_type '{target_type}'."
            )

        target_assistant = await self._load_target_with_edit_permission(target_id)

        role = await self.role_service.get_active(kind)
        if role is None or not role.is_enabled or not role.is_visible_to_users:
            raise UnauthorizedException(
                f"Help assistant '{kind.value}' is not available.",
                code="helper_not_available",
            )

        helper_assistant = await self._load_helper_assistant(role.assistant_id)
        self._check_helper_completion_model(helper_assistant)

        session = await self._create_helper_session(
            helper_assistant_id=helper_assistant.id, question=question
        )

        run_entity = self.factory.create_helper_run(
            tenant_id=self.user.tenant_id,
            org_space_id=role.org_space_id,
            kind=kind,
            assistant_id=helper_assistant.id,
            target_type=target_type,
            target_id=target_assistant.id,
            session_id=session.id,
            actor_user_id=self.user.id,
            status=HelperRunStatus.IN_PROGRESS,
        )
        run = await self.helper_run_repo.add(run_entity)

        # PRD §6.5: helper runs use ONLY the helper assistant's tools/knowledge.
        # Do not forward anything from target_assistant — silent inheritance is
        # the specific failure mode this design rules out.
        datastore_result = await self.references_service.get_references(
            question=question,
            session=session,
            collections=list(helper_assistant.collections),
            websites=list(helper_assistant.websites),
            integration_knowledge_list=list(
                helper_assistant.integration_knowledge_list
            ),
        )

        assert helper_assistant.completion_model is not None
        completion_model = cast("AICompletionModel", helper_assistant.completion_model)
        response = await self.completion_service.get_response(
            model=completion_model,
            text_input=question,
            prompt=helper_assistant.get_prompt_text(),
            prompt_files=helper_assistant.attachments,
            info_blob_chunks=datastore_result.chunks,
            session=session,
            stream=stream,
            # PRD §6 + Critical test #3: helper runs never produce extended
            # logging or insights aggregation, regardless of the helper
            # assistant's stored ``logging_enabled`` / ``insight_enabled``.
            extended_logging=False,
            model_kwargs=helper_assistant.completion_model_kwargs,
            mcp_servers=(
                []
                if helper_assistant.has_knowledge()
                else list(helper_assistant.mcp_servers)
            ),
        )

        if stream:
            return HelperRunResponse(
                run=run,
                session=session,
                answer=self._stream_and_persist(
                    response=response,
                    session=session,
                    question=question,
                    datastore_chunks=datastore_result.no_duplicate_chunks,
                    helper_assistant=helper_assistant,
                ),
                info_blobs=datastore_result.info_blobs,
            )

        answer_text = await self._persist_answer(
            response=response,
            session=session,
            question=question,
            datastore_chunks=datastore_result.no_duplicate_chunks,
            helper_assistant=helper_assistant,
        )

        return HelperRunResponse(
            run=run,
            session=session,
            answer=answer_text,
            info_blobs=datastore_result.info_blobs,
        )

    async def continue_turn(
        self,
        *,
        run_id: UUID,
        question: str,
        stream: bool = False,
    ) -> HelperRunResponse:
        """Append a follow-up turn to an existing helper run.

        Reuses the run's ``session_id`` so prior conversation context flows
        into the completion call. Re-runs the availability / actor / model
        checks every turn — admins may toggle role enablement between turns,
        and a previously-working completion model can be removed. Same
        ``extended_logging=False`` rule as :meth:`run`. Does **not** mutate
        ``run.status`` (status transitions are user-driven via
        :meth:`set_status`).
        """
        run = await self._load_run_for_actor(run_id)

        role = await self.role_service.get_active(run.kind)
        if role is None or not role.is_enabled or not role.is_visible_to_users:
            raise UnauthorizedException(
                f"Help assistant '{run.kind.value}' is not available.",
                code="helper_not_available",
            )

        if run.assistant_id is None:
            raise NotFoundException(
                "Helper assistant for this run is no longer available."
            )
        helper_assistant = await self._load_helper_assistant(run.assistant_id)
        self._check_helper_completion_model(helper_assistant)

        session = await self.session_repo.get_for_helper_run(
            run.session_id, self.user.tenant_id
        )
        if session is None:
            raise NotFoundException("Helper run session not found.")

        # PRD §6.5: helper runs use ONLY the helper assistant's tools/knowledge.
        # Do not forward anything from target_assistant — silent inheritance is
        # the specific failure mode this design rules out.
        datastore_result = await self.references_service.get_references(
            question=question,
            session=session,
            collections=list(helper_assistant.collections),
            websites=list(helper_assistant.websites),
            integration_knowledge_list=list(
                helper_assistant.integration_knowledge_list
            ),
        )

        assert helper_assistant.completion_model is not None
        completion_model = cast("AICompletionModel", helper_assistant.completion_model)
        response = await self.completion_service.get_response(
            model=completion_model,
            text_input=question,
            prompt=helper_assistant.get_prompt_text(),
            prompt_files=helper_assistant.attachments,
            info_blob_chunks=datastore_result.chunks,
            session=session,
            stream=stream,
            # PRD §6 + Critical test #3: same hard-coded gate as run().
            extended_logging=False,
            model_kwargs=helper_assistant.completion_model_kwargs,
            mcp_servers=(
                []
                if helper_assistant.has_knowledge()
                else list(helper_assistant.mcp_servers)
            ),
        )

        if stream:
            return HelperRunResponse(
                run=run,
                session=session,
                answer=self._stream_and_persist(
                    response=response,
                    session=session,
                    question=question,
                    datastore_chunks=datastore_result.no_duplicate_chunks,
                    helper_assistant=helper_assistant,
                ),
                info_blobs=datastore_result.info_blobs,
            )

        answer_text = await self._persist_answer(
            response=response,
            session=session,
            question=question,
            datastore_chunks=datastore_result.no_duplicate_chunks,
            helper_assistant=helper_assistant,
        )

        return HelperRunResponse(
            run=run,
            session=session,
            answer=answer_text,
            info_blobs=datastore_result.info_blobs,
        )

    async def set_status(
        self,
        *,
        run_id: UUID,
        status: HelperRunStatus,
    ) -> HelperRun:
        """Move an in-progress run to a terminal status.

        UX-driven: ``COMPLETED`` is set by the modal's Apply button,
        ``ABANDONED`` by closing the modal without applying, ``FAILED`` by
        the router when a completion call blows up mid-stream. Only the
        original actor may transition their own run, and only from
        ``IN_PROGRESS`` — repeat transitions or "un-completing" a run are
        rejected. No audit log entry: the row itself is the record.
        """
        run = await self._load_run_for_actor(run_id)

        if status == HelperRunStatus.IN_PROGRESS:
            raise BadRequestException(
                "Cannot set helper-run status to 'in_progress'; only "
                "terminal statuses are allowed."
            )

        if run.status != HelperRunStatus.IN_PROGRESS:
            raise BadRequestException(
                f"Cannot transition helper run from '{run.status.value}' "
                f"to '{status.value}'; only IN_PROGRESS runs may transition."
            )

        completed_at = datetime.now(timezone.utc)
        updated = await self.helper_run_repo.update_status(
            id=run_id,
            tenant_id=self.user.tenant_id,
            status=status,
            completed_at=completed_at,
            expected_status=HelperRunStatus.IN_PROGRESS,
        )
        if updated is None:
            # Lost a race: another request moved this run out of IN_PROGRESS
            # between the pre-check above and this UPDATE. The conditional
            # UPDATE is the real guard; surface the same error as the
            # pre-check so two terminal transitions cannot both "win".
            raise BadRequestException(
                f"Cannot transition helper run to '{status.value}'; "
                "the run is no longer in progress."
            )
        return updated

    async def _load_run_for_actor(self, run_id: UUID) -> HelperRun:
        run = await self.helper_run_repo.get_by_id(run_id, self.user.tenant_id)
        if run is None:
            raise NotFoundException("Helper run not found.")
        if run.actor_user_id != self.user.id:
            raise UnauthorizedException(
                "You do not have permission to access this helper run.",
                code="forbidden_action",
            )
        return run

    async def _load_target_with_edit_permission(self, target_id: UUID) -> Assistant:
        target_assistant, permissions = await self.assistant_service.get_assistant(
            assistant_id=target_id
        )
        if ResourcePermission.EDIT not in permissions:
            raise UnauthorizedException(
                "You do not have permission to use a helper on this assistant.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "helper_run",
                    "auth_layer": "domain_policy",
                },
            )
        return target_assistant

    async def _load_helper_assistant(self, assistant_id: UUID) -> Assistant:
        # PRIVILEGED helper read (PRD §5/§6/§10). The helper assistant lives in
        # the org-space, whose only members are tenant admins, so the normal
        # permission-enforcing assistant_service.get_assistant would 403 for
        # every non-admin end user. End-user authorization for a helper run is
        # the EDIT check on the *target* assistant
        # (_load_target_with_edit_permission) plus the role's is_enabled /
        # is_visible_to_users flags — both enforced above — NOT org-space
        # membership. get_help_assistant keeps the read scoped to the assistant
        # designated by the (active or former) help-assistant role.
        return await self.assistant_service.get_help_assistant(assistant_id)

    def _check_helper_completion_model(self, helper: Assistant) -> None:
        if helper.completion_model is None:
            raise BadRequestException(
                "Help assistant has no completion model configured. "
                "An admin must pick one before this helper can run."
            )
        if not helper.completion_model.can_access:
            raise UnauthorizedException(
                "Help assistant's completion model is not accessible.",
                code="forbidden_action",
            )

    async def _create_helper_session(
        self, *, helper_assistant_id: UUID, question: str
    ) -> SessionInDB:
        # Sessions.name has no length cap at the schema layer, but matching
        # what assistant_service.ask does (uses the question verbatim) keeps
        # the row shape consistent with non-helper conversations. The session
        # is hidden from every listing anyway via the helper-run filter.
        return await self.session_repo.add(
            SessionAdd(
                name=question,
                user_id=self.user.id,
                assistant_id=helper_assistant_id,
            )
        )

    async def _persist_answer(
        self,
        *,
        response: CompletionModelResponse,
        session: SessionInDB,
        question: str,
        datastore_chunks: list[InfoBlobChunkInDBWithScore],
        helper_assistant: Assistant,
    ) -> str:
        # Mirror session_service.add_question_to_session inline so we never
        # accidentally route through code paths that aggregate insights or
        # write to the logging table. ``logging_details`` is always ``None``
        # because we forced ``extended_logging=False`` upstream.
        completion = response.completion
        if isinstance(completion, str):
            final_answer = completion
        elif completion is None:
            final_answer = ""
        else:
            final_answer = getattr(completion, "text", "") or ""

        usage = getattr(response, "usage", None)
        if usage is not None and usage.prompt_tokens is not None:
            num_tokens_question = usage.prompt_tokens
        else:
            num_tokens_question = response.total_token_count

        if usage is not None and usage.completion_tokens is not None:
            num_tokens_answer = usage.completion_tokens
        else:
            num_tokens_answer = 0

        assert helper_assistant.completion_model is not None
        question_add = QuestionAdd(
            tenant_id=self.user.tenant_id,
            question=question,
            answer=final_answer,
            num_tokens_question=num_tokens_question,
            num_tokens_answer=num_tokens_answer,
            completion_model_id=helper_assistant.completion_model.id,
            session_id=session.id,
            logging_details=None,
            assistant_id=helper_assistant.id,
        )
        await self.question_repo.add(
            question_add,
            info_blob_chunks=list(datastore_chunks),
        )
        return final_answer

    async def _stream_and_persist(
        self,
        *,
        response: CompletionModelResponse,
        session: SessionInDB,
        question: str,
        datastore_chunks: list[InfoBlobChunkInDBWithScore],
        helper_assistant: Assistant,
    ) -> AsyncGenerator[Completion, None]:
        """Yield streaming chunks and persist the assembled answer at close.

        Mirrors the non-stream ``_persist_answer`` contract: at end of stream
        the question + answer + token counts are written to
        ``questions_repo`` with ``logging_details=None`` so no row reaches
        the ``logging`` table (PRD §6 + Critical test #3). Token counts
        prefer provider-reported values from the final ``TokenUsage`` chunk
        and fall back to ``response.total_token_count`` if absent —
        matching the assistant-service pattern.

        The persistence call wraps a defensive ``session.begin()`` when the
        request-scoped transaction has already committed — same idiom as
        ``SessionService._write_transaction``. Streaming responses dispatch
        their body iterator outside the request-level transaction in some
        execution paths, so the persistence has to open its own short
        write transaction whenever one is not already active.
        """

        completion = response.completion
        if isinstance(completion, str) or completion is None:
            return

        response_string = ""
        stream_usage: TokenUsage | None = None

        async for chunk in completion:
            if chunk.usage is not None:
                stream_usage = chunk.usage
            if chunk.response_type == ResponseType.TEXT and chunk.text is not None:
                response_string = f"{response_string}{chunk.text}"
            yield chunk

        if stream_usage is not None and stream_usage.prompt_tokens is not None:
            num_tokens_question = stream_usage.prompt_tokens
        else:
            num_tokens_question = response.total_token_count

        if stream_usage is not None and stream_usage.completion_tokens is not None:
            num_tokens_answer = stream_usage.completion_tokens
        else:
            num_tokens_answer = 0

        assert helper_assistant.completion_model is not None
        question_add = QuestionAdd(
            tenant_id=self.user.tenant_id,
            question=question,
            answer=response_string,
            num_tokens_question=num_tokens_question,
            num_tokens_answer=num_tokens_answer,
            completion_model_id=helper_assistant.completion_model.id,
            session_id=session.id,
            logging_details=None,
            assistant_id=helper_assistant.id,
        )

        repo_session = self.question_repo.session
        if repo_session.in_transaction():
            await self.question_repo.add(
                question_add,
                info_blob_chunks=list(datastore_chunks),
            )
        else:
            async with repo_session.begin():
                await self.question_repo.add(
                    question_add,
                    info_blob_chunks=list(datastore_chunks),
                )
