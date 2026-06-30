from typing import Annotated

from fastapi import Depends

from eneo.database.database import AsyncSession, get_session_with_transaction
from eneo.questions.questions_repo import QuestionRepository


def get_questions_repo(
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
) -> QuestionRepository:
    return QuestionRepository(session)
