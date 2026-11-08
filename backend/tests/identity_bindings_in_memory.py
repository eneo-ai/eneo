"""``IdentityBindingRepository`` in memory, for unit tests that admit
federated users without a database. The integration suites run the real
repository, its constraints and its locks."""

from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from eneo.users.identity_binding_repo import IdentityBinding


class IdentityBindingsInMemory:
    def __init__(self) -> None:
        # (tenant_id, user_id, binding)
        self.rows: list[tuple[UUID, UUID, IdentityBinding]] = []
        # Accounts an admin allowed to take a new identity by email.
        self.rebinding: set[UUID] = set()

    async def holder(
        self, *, tenant_id: UUID, issuer: str, audience: str, subject: str
    ) -> UUID | None:
        return next(
            (
                user_id
                for tenant, user_id, binding in self.rows
                if tenant == tenant_id
                and (binding.issuer, binding.audience, binding.subject)
                == (issuer, audience, subject)
            ),
            None,
        )

    async def holders_of_subject(
        self, *, tenant_id: UUID, issuer: str, subject: str
    ) -> list[UUID]:
        holders = {
            user_id
            for tenant, user_id, binding in self.rows
            if tenant == tenant_id
            and (binding.issuer, binding.subject) == (issuer, subject)
        }
        return sorted(holders)[:2]

    async def of_user(self, user_id: UUID) -> list[IdentityBinding]:
        return [binding for _, user, binding in self.rows if user == user_id]

    async def bind(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        issuer: str,
        audience: str,
        subject: str,
    ) -> bool:
        taken = await self.holder(
            tenant_id=tenant_id, issuer=issuer, audience=audience, subject=subject
        )
        if taken is not None or any(
            (binding.issuer, binding.audience) == (issuer, audience)
            for binding in await self.of_user(user_id)
        ):
            return False
        binding = IdentityBinding(issuer, audience, subject, datetime.now(timezone.utc))
        self.rows.append((tenant_id, user_id, binding))
        return True

    async def unbind(self, *, user_id: UUID, issuer: str, audience: str) -> None:
        self.rows = [
            row
            for row in self.rows
            if not (
                row[1] == user_id
                and (row[2].issuer, row[2].audience) == (issuer, audience)
            )
        ]

    async def open_window(
        self,
        *,
        tenant_id: UUID,
        to_issuer: str,
        to_audience: str,
        from_pairs: Iterable[tuple[str, str]],
        opened_after: datetime | None = None,
    ) -> UUID | None:
        return None

    async def rebinding_open(self, user_id: UUID) -> bool:
        return user_id in self.rebinding

    async def close_rebinding(self, user_id: UUID) -> None:
        self.rebinding.discard(user_id)
