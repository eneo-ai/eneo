from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.websites.crawl_dependencies.crawl_models import CrawlTask


@pytest.mark.parametrize(
    ("attempt_id", "attempt_number"),
    [(uuid4(), None), (None, 1)],
)
def test_attempt_identity_requires_both_id_and_number(
    attempt_id: UUID | None,
    attempt_number: int | None,
) -> None:
    with pytest.raises(ValidationError, match="attempt_id and attempt_number"):
        CrawlTask(
            user_id=uuid4(),
            website_id=uuid4(),
            run_id=uuid4(),
            url="https://example.com",
            attempt_id=attempt_id,
            attempt_number=attempt_number,
        )
