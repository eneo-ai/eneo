from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.logging_table import logging_table
from eneo.database.tables.mcp_tool_references_table import (
    McpToolReference as McpToolReferencesTable,
)
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.database.tables.web_search_results_table import (
    WebSearchResult as WebSearchResultsTable,
)
from eneo.files.file_models import File
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.questions.question import Question, QuestionAdd

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import McpToolReference
    from eneo.completion_models.infrastructure.web_search import WebSearchResult
    from eneo.logging.logging import LoggingDetails
    from eneo.questions.question import ToolCallInfo


class QuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[Question] = BaseRepositoryDelegate(
            session,
            Questions,
            Question,
            with_options=self._get_options(),
        )
        self.session = session

    def _get_options(self):
        return [
            selectinload(Questions.completion_model),
            selectinload(Questions.info_blob_references)
            .selectinload(InfoBlobReferences.info_blob)
            .selectinload(InfoBlobs.group),
            selectinload(Questions.logging_details),
            selectinload(Questions.assistant),
            selectinload(Questions.session),
            selectinload(Questions.questions_files).selectinload(QuestionsFiles.file),
            selectinload(Questions.info_blob_references)
            .selectinload(InfoBlobReferences.info_blob)
            .selectinload(InfoBlobs.website),
            selectinload(Questions.web_search_results),
            selectinload(Questions.mcp_tool_references),
        ]

    def _add_options(
        self, stmt: sa.Select[tuple[Any]] | sa.Insert | sa.Update
    ) -> sa.Select[tuple[Any]] | sa.Insert | sa.Update:
        for option in self._get_options():
            stmt = stmt.options(option)

        return stmt

    async def _get_info_blob_record(self, id: str):
        stmt = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.id == id)
            .options(selectinload(InfoBlobs.group))
        )

        return await self.session.scalar(stmt)

    async def _add_references(
        self, question_id: int, chunks: list[InfoBlobChunkInDBWithScore]
    ) -> list[InfoBlobReferences]:
        if not chunks:
            return []

        stmt = (
            sa.insert(InfoBlobReferences)
            .values(
                [
                    dict(
                        question_id=question_id,
                        info_blob_id=chunk.info_blob_id,
                        similarity_score=chunk.score,
                        order=i,
                    )
                    for i, chunk in enumerate(chunks)
                ]
            )
            .returning(InfoBlobReferences)
        )

        return list((await self.session.scalars(stmt)).all())

    async def _add_files(
        self, question_id: int, files: list[File], file_type: str = "user"
    ):
        stmt = sa.insert(QuestionsFiles).values(
            [
                dict(question_id=question_id, file_id=file.id, type=file_type)
                for file in files
            ]
        )

        await self.session.execute(stmt)

    async def _add_web_search_results(
        self, web_search_results: list["WebSearchResult"], question_id: UUID
    ):
        stmt = sa.insert(WebSearchResultsTable).values(
            [
                dict(
                    id=web_search_result.id,
                    title=web_search_result.title,
                    url=web_search_result.url,
                    content=web_search_result.content,
                    score=web_search_result.score,
                    question_id=question_id,
                )
                for web_search_result in web_search_results
            ]
        )

        await self.session.execute(stmt)

    async def _add_mcp_tool_references(
        self, mcp_tool_references: list["McpToolReference"], question_id: UUID
    ):
        stmt = sa.insert(McpToolReferencesTable).values(
            [
                dict(
                    id=ref.id,
                    question_id=question_id,
                    tool_call_id=ref.tool_call_id,
                    mcp_tool_name=ref.mcp_tool_name,
                    uri=ref.uri,
                    mime_type=ref.mime_type,
                    content=ref.content,
                    meta=ref.meta,
                    order=ref.order,
                )
                for ref in mcp_tool_references
            ]
        )

        await self.session.execute(stmt)

    async def get(self, id: UUID):
        return await self.delegate.get(id)

    async def update_with_answer(
        self,
        *,
        question_id: UUID,
        tenant_id: UUID,
        answer: str,
        num_tokens_question: int | None = None,
        num_tokens_answer: int | None = None,
        completion_model_id: UUID | None = None,
        tool_calls: list["ToolCallInfo"] | None = None,
        reasoning: str | None = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        generated_files: list[File] | None = None,
        web_search_results: list["WebSearchResult"] | None = None,
        logging_details: "LoggingDetails | None" = None,
        mcp_tool_references: list["McpToolReference"] | None = None,
    ) -> None:
        """Update an existing placeholder Question row with the final or partial answer.

        Used both for normal stream completion (full answer + token counts + late-bound rows)
        and for partial persistence on abort (just the answer text + estimated token counts).

        tenant_id is required in the WHERE clause to defend against cross-tenant writes if a
        caller ever supplies a stale question_id.
        """
        logging_details_id: object = None
        if logging_details is not None:
            log_stmt = (  # pyright: ignore[reportUnknownVariableType]  # logging_table is imperatively mapped
                sa.insert(logging_table)
                .values(**logging_details.model_dump())
                .returning(logging_table)
            )
            log_result = await self.session.execute(log_stmt)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
            logging_row = log_result.scalar_one()  # pyright: ignore[reportUnknownVariableType]
            logging_details_id = logging_row.id  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

        update_values: dict[str, Any] = {"answer": answer}
        if num_tokens_question is not None:
            update_values["num_tokens_question"] = num_tokens_question
        if num_tokens_answer is not None:
            update_values["num_tokens_answer"] = num_tokens_answer
        if completion_model_id is not None:
            update_values["completion_model_id"] = completion_model_id
        if tool_calls is not None:
            update_values["tool_calls"] = [tc.model_dump() for tc in tool_calls]
        if reasoning is not None:
            update_values["reasoning"] = reasoning
        if logging_details_id is not None:
            update_values["logging_details_id"] = logging_details_id

        update_stmt = (
            sa.update(Questions)
            .where(Questions.id == question_id)
            .where(Questions.tenant_id == tenant_id)
            .values(**update_values)
        )
        await self.session.execute(update_stmt)

        if info_blob_chunks:
            await self._add_references(
                question_id=question_id,  # type: ignore[arg-type]  # helper annotated as int but ID is UUID
                chunks=info_blob_chunks,
            )
        if generated_files:
            await self._add_files(
                question_id=question_id,  # type: ignore[arg-type]  # helper annotated as int but ID is UUID
                files=list(generated_files),
                file_type="assistant",
            )
        if web_search_results:
            await self._add_web_search_results(
                web_search_results=list(web_search_results),
                question_id=question_id,
            )
        if mcp_tool_references:
            await self._add_mcp_tool_references(
                mcp_tool_references=mcp_tool_references,
                question_id=question_id,
            )

    async def add(
        self,
        question: QuestionAdd,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        files: list[File] | None = None,
        generated_files: list[File] | None = None,
        web_search_results: list["WebSearchResult"] | None = None,
        mcp_tool_references: list["McpToolReference"] | None = None,
    ):
        stmt = (
            sa.insert(Questions)
            .values(**question.model_dump(exclude={"info_blobs", "logging_details"}))
            .returning(Questions)
        )

        stmt = self._add_options(stmt)

        question_record = await self.session.scalar(stmt)

        question_record.info_blob_references = await self._add_references(
            question_id=question_record.id, chunks=info_blob_chunks or []
        )

        if files:
            await self._add_files(
                question_id=question_record.id, files=files, file_type="user"
            )

        if generated_files:
            await self._add_files(
                question_id=question_record.id,
                files=generated_files,
                file_type="assistant",
            )

        if web_search_results:
            await self._add_web_search_results(
                web_search_results=web_search_results, question_id=question_record.id
            )

        if mcp_tool_references:
            await self._add_mcp_tool_references(
                mcp_tool_references=mcp_tool_references,
                question_id=question_record.id,
            )

        if question.logging_details is not None:
            stmt = (  # pyright: ignore[reportUnknownVariableType]  # logging_table type is dynamically created and not fully typed
                sa.insert(logging_table)
                .values(**question.logging_details.model_dump())
                .returning(logging_table)
            )
            result = await self.session.execute(stmt)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]  # logging_table dynamic type
            logging_details = result.scalar_one()  # pyright: ignore[reportUnknownVariableType]  # dynamic table scalar
            question_record.logging_details = logging_details

        return await self.get(question_record.id)

    async def get_by_service(self, service_id: UUID):
        stmt = (
            sa.select(Questions)
            .where(Questions.service_id == service_id)
            # Helper-assistant questions must never surface in exports/analysis
            # (PRD §4) — same exclusion as sessions_repo / analysis_repo.
            .where(
                ~sa.exists(
                    sa.select(HelpAssistantRuns.id).where(
                        HelpAssistantRuns.session_id == Questions.session_id
                    )
                )
            )
            .order_by(Questions.created_at)
        )

        return await self.delegate.get_models_from_query(stmt)

    async def get_by_tenant(
        self, tenant_id: UUID, start_date: datetime, end_date: datetime
    ):
        stmt = (
            sa.select(Questions)
            .where(Questions.session_id.is_not(None))
            .join(Sessions)
            .join(Users)
            .where(Users.tenant_id == tenant_id)
            # Exclude helper-assistant questions from tenant-wide exports.
            .where(
                ~sa.exists(
                    sa.select(HelpAssistantRuns.id).where(
                        HelpAssistantRuns.session_id == Sessions.id
                    )
                )
            )
            .filter(Questions.created_at >= start_date)
            .filter(Questions.created_at <= end_date)
            .order_by(Questions.created_at)
        )

        return await self.delegate.get_models_from_query(stmt)
