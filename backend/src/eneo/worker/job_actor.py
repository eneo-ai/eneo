"""Who a queued job runs as in the worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

if TYPE_CHECKING:
    from eneo.main.container.container import Container
    from eneo.users.user import UserInDB


@dataclass(frozen=True, slots=True)
class JobActor:
    """Who a job runs as, read from its params: a person, a service key, or a
    space doing its own scheduled work."""

    user_id: UUID | None = None
    api_key_id: UUID | None = None
    tenant_id: UUID | None = None
    acting_space_id: UUID | None = None

    @classmethod
    def of(cls, params: object) -> JobActor:
        return cls(
            user_id=cast("UUID | None", getattr(params, "user_id", None)),
            api_key_id=cast("UUID | None", getattr(params, "api_key_id", None)),
            tenant_id=cast("UUID | None", getattr(params, "tenant_id", None)),
            acting_space_id=cast(
                "UUID | None", getattr(params, "acting_space_id", None)
            ),
        )

    @property
    def is_service_key(self) -> bool:
        return (
            self.user_id is None
            and self.api_key_id is not None
            and self.tenant_id is not None
        )

    @property
    def is_space(self) -> bool:
        return (
            self.user_id is None
            and self.acting_space_id is not None
            and self.tenant_id is not None
        )

    @property
    def present(self) -> bool:
        return self.user_id is not None or self.is_service_key or self.is_space


async def load_job_user(container: Container, actor: JobActor) -> UserInDB | None:
    """The user a job runs as, or None when that caller no longer has access:
    a removed person, a revoked or expired key, a disabled service principal.

    A service key's user is the same made-up user the key signs in as on a
    request, so the job has exactly the key's rights and nothing is stored as
    a pretend person. A space's own job runs with that space's rights; it is
    gone when the space is.
    """
    if actor.user_id is not None:
        return await container.user_repo().get_user_by_id(id=actor.user_id)
    if actor.acting_space_id is not None and actor.tenant_id is not None:
        return await container.user_service().get_space_actor_user(
            space_id=actor.acting_space_id, tenant_id=actor.tenant_id
        )
    if actor.api_key_id is not None and actor.tenant_id is not None:
        return await container.user_service().get_service_key_user(
            key_id=actor.api_key_id, tenant_id=actor.tenant_id
        )
    return None
