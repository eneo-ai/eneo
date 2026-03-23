from unittest.mock import AsyncMock, MagicMock

from intric.ai_models.completion_models.completion_model import Completion
from intric.apps.app_runs.app_run_service import AppRunService
from intric.completion_models.infrastructure.context_builder import count_tokens


async def test_update_tokens_in_run():
    # Setup
    app_run_service = AppRunService(
        MagicMock(id=1), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock()
    )

    app_run = MagicMock(user_id=1)
    app_run_service.repo.get.return_value = app_run

    completion = Completion(text="This is the output!")
    app_run_service.app_service.run_app.return_value = MagicMock(
        completion=completion, total_token_count=10, usage=None
    )

    # Execute
    await app_run_service.run_app(MagicMock(), MagicMock(), MagicMock(), MagicMock())

    # Assert
    num_tokens_output = count_tokens(completion.text)
    app_run.update.assert_called_once_with(
        output=completion.text,
        num_tokens_input=10,
        num_tokens_output=num_tokens_output,
    )
