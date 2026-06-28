from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )


class CompletionModelService:
    def __init__(self, completion_model_repo: "CompletionModelRepository"):
        super().__init__()
        self.completion_model_repo = completion_model_repo

    async def get_available_completion_models(self):
        completion_models = await self.completion_model_repo.all()

        return [model for model in completion_models if model.can_access]
