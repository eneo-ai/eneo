from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from intric.worker.crawl.audit import CrawlAuditPayload, record_crawl_audit
from intric.worker.crawl.circuit_breaker import update_crawl_circuit_breaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.audit.application.audit_service import AuditService


class PostTerminalRecoveryExecutor(Protocol):
    async def __call__(
        self,
        *,
        operation_name: str,
        operation: Callable[["AsyncSession"], Awaitable[None]],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PostTerminalRecoveryContext:
    execute_with_recovery: PostTerminalRecoveryExecutor


@dataclass(frozen=True, slots=True)
class PostTerminalEffectInput:
    recovery: PostTerminalRecoveryContext
    audit_service: "AuditService"
    audit_payload: CrawlAuditPayload
    circuit_breaker_operation_name: Literal[
        "terminal_circuit_breaker_update",
        "circuit_breaker_update",
    ]


async def apply_post_terminal_effects(effect: PostTerminalEffectInput) -> None:
    payload = effect.audit_payload
    recovery = effect.recovery

    async def _do_circuit_breaker_update(sess: "AsyncSession") -> None:
        await update_crawl_circuit_breaker(
            sess,
            website_id=payload.website_id,
            tenant_id=payload.tenant_id,
            website_url=payload.website_url,
            crawl_successful=payload.successful,
        )

    await recovery.execute_with_recovery(
        operation_name=effect.circuit_breaker_operation_name,
        operation=_do_circuit_breaker_update,
    )
    await record_crawl_audit(
        effect.audit_service,
        payload,
    )
