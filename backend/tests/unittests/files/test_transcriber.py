from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_models import File
from eneo.files.transcriber import Transcriber


@pytest.mark.asyncio
async def test_transcribe_returns_the_durable_winner_from_a_racing_write() -> None:
    file_service = MagicMock()
    file_service.save_transcription = AsyncMock(return_value="durable winner")
    transcriber = Transcriber(file_service)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="provider result")
    file = File.model_construct(
        id=uuid4(),
        blob=b"audio",
        mimetype="audio/mpeg",
        transcription=None,
    )

    result = await transcriber.transcribe(file, MagicMock())

    assert result == "durable winner"
    file_service.save_transcription.assert_awaited_once_with(
        file.id,
        "provider result",
    )
