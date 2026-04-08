from typing import Annotated, Callable, Protocol, TypeVar

from fastapi import Depends

from intric.database.database import AsyncSession, get_session_with_transaction

RepoT_co = TypeVar("RepoT_co", covariant=True)


class RepositoryFactory(Protocol[RepoT_co]):
    def __call__(self, session: AsyncSession) -> RepoT_co: ...


def get_repository(
    repo_type: RepositoryFactory[RepoT_co],
) -> Callable[..., RepoT_co]:
    def get_repo(
        db: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    ) -> RepoT_co:
        return repo_type(db)

    return get_repo
