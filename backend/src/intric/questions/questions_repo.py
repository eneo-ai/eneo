from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.logging_table import logging_table
from intric.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.users_table import Users
from intric.database.tables.web_search_results_table import (
    WebSearchResult as WebSearchResultsTable,
)
from intric.files.file_models import File
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.questions.question import Question, QuestionAdd

if TYPE_CHECKING:
    from intric.completion_models.infrastructure.web_search import WebSearchResult


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

    async def get(self, id: UUID):
        return await self.delegate.get(id)

    async def add(
        self,
        question: QuestionAdd,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        files: list[File] | None = None,
        generated_files: list[File] | None = None,
        web_search_results: list["WebSearchResult"] | None = None,
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
            .filter(Questions.created_at >= start_date)
            .filter(Questions.created_at <= end_date)
            .order_by(Questions.created_at)
        )

        return await self.delegate.get_models_from_query(stmt)
