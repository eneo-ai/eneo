import uuid

import wrapt

from intric.database.database import AsyncSession
from intric.main.logging import get_logger

logger = get_logger(__name__)


def gen_transaction(session: AsyncSession):
    @wrapt.decorator
    async def _inner(func, instance, args, kwargs):
        transaction_id = uuid.uuid4()
        logger.debug(f"Starting database transaction: {transaction_id}")

        async with session.begin():
            async for i in func(*args, **kwargs):
                yield i

        logger.debug(f"Transaction {transaction_id} ended")

    return _inner
