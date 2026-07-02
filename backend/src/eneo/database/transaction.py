import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import wrapt

from eneo.database.database import AsyncSession
from eneo.main.logging import get_logger

logger = get_logger(__name__)


def gen_transaction(
    session: AsyncSession,
) -> Any:
    wrapt_decorator: Any = getattr(wrapt, "decorator")

    @wrapt_decorator
    async def _inner(
        func: Callable[..., AsyncIterator[Any]],
        _instance: object,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> AsyncIterator[Any]:
        transaction_id = uuid.uuid4()
        logger.debug(f"Starting database transaction: {transaction_id}")

        async with session.begin():
            async for item in func(*args, **kwargs):
                yield item

        logger.debug(f"Transaction {transaction_id} ended")

    return _inner
