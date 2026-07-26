from typing import Annotated

from fastapi import Depends

from eneo.main.container.container import Container
from eneo.questions.questions_repo import QuestionRepository
from eneo.server.dependencies.container import get_container


def get_questions_repo(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> QuestionRepository:
    return container.question_repo()
