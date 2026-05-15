from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from intric.worker.crawl.audit import CrawlAuditPayload, record_crawl_audit
from intric.worker.crawl.circuit_breaker import update_crawl_circuit_breaker
from intric.worker.crawl.recovery import SessionHolder

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.main.container.container import Container


class PostTerminalRecoveryExecutor(Protocol):
    async def __call__(
        self,
        *,
        container: "Container",
        session_holder: SessionHolder,
        created_sessions: list["AsyncSession"],
        operation_name: str,
        operation: Callable[["AsyncSession"], Awaitable[None]],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PostTerminalRecoveryContext:
    container: "Container"
    session_holder: SessionHolder
    created_sessions: list["AsyncSession"]
    execute_with_recovery: PostTerminalRecoveryExecutor


@dataclass(frozen=True, slots=True)
class PostTerminalReactionInput:
    recovery: PostTerminalRecoveryContext
    audit_payload: CrawlAuditPayload
    circuit_breaker_operation_name: Literal[
        "terminal_circuit_breaker_update",
        "circuit_breaker_update",
    ]


async def apply_post_terminal_reactors(reaction: PostTerminalReactionInput) -> None:
    payload = reaction.audit_payload
    recovery = reaction.recovery

    async def _do_circuit_breaker_update(sess: "AsyncSession") -> None:
        await update_crawl_circuit_breaker(
            sess,
            website_id=payload.website_id,
            tenant_id=payload.tenant_id,
            website_url=payload.website_url,
            crawl_successful=payload.successful,
        )

    await recovery.execute_with_recovery(
        container=recovery.container,
        session_holder=recovery.session_holder,
        created_sessions=recovery.created_sessions,
        operation_name=reaction.circuit_breaker_operation_name,
        operation=_do_circuit_breaker_update,
    )
    await record_crawl_audit(
        recovery.container.audit_service(),
        payload,
    )
