from openai import AsyncOpenAI

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.completion_models.infrastructure import get_response_open_ai
from intric.main.config import SETTINGS


class GeminiModelAdapter(OpenAIModelAdapter):
    """
    Adapter for Google Gemini models using OpenAI-compatible API.
    
    This adapter extends OpenAIModelAdapter because Gemini provides an 
    OpenAI-compatible endpoint. Changes to OpenAIModelAdapter may affect
    this adapter, but this is intentional as they share the same API interface.
    
    Reasoning Support (Stable Versions):
    - gemini-2.0-flash: No reasoning support
    - gemini-2.0-flash-lite: No reasoning support
    - gemini-2.5-flash: Optional reasoning (user-controlled on/off and intensity)
    - gemini-2.5-flash-lite: Optional reasoning (user-controlled on/off and intensity, same as 2.5-flash)
    - gemini-2.5-pro: Always-on reasoning (intensity user-controlled)
    """
    
    GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    
    def __init__(self, model: CompletionModel):
        self.model = model
        self.client = AsyncOpenAI(
            api_key=SETTINGS.gemini_api_key,
            base_url=self.GEMINI_BASE_URL
        )
        self.extra_headers = None
    
    def _get_correct_model_name(self) -> str:
        """
        Map model names to correct stable API model names.
        
        This handles the transition from preview versions to stable versions,
        ensuring backward compatibility with existing database entries.
        """
        model_name_mapping = {
            # Stable versions (pass through)
            "gemini-2.5-flash": "gemini-2.5-flash",
            "gemini-2.5-pro": "gemini-2.5-pro",
            "gemini-2.0-flash": "gemini-2.0-flash",
            "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
            "gemini-2.0-flash-lite": "gemini-2.0-flash-lite",
            
            # Map preview versions to stable versions for backward compatibility
            "gemini-2.5-flash-preview-05-20": "gemini-2.5-flash",
            "gemini-2.5-pro-preview-06-05": "gemini-2.5-pro",
            "gemini-2.5-flash-lite-06-17": "gemini-2.5-flash-lite",
            "gemini-2.0-flash-001": "gemini-2.0-flash",
            "gemini-2.0-flash-lite-001": "gemini-2.0-flash-lite"
        }
        
        return model_name_mapping.get(self.model.name, self.model.name)
    
    def _model_supports_reasoning(self) -> bool:
        """
        Check if the current Gemini model supports reasoning/thinking parameters.
        
        Based on Google's Gemini API documentation:
        - gemini-2.0-flash: No reasoning support
        - gemini-2.0-flash-lite: No reasoning support
        - gemini-2.5-flash: Optional reasoning support (user can enable/disable)
        - gemini-2.5-flash-lite: Optional reasoning support (user can enable/disable, same as 2.5-flash)
        - gemini-2.5-pro: Reasoning support (always-on for Pro)
        
        Returns:
            bool: True if model supports reasoning_effort parameter
        """
        # Get the mapped stable model name
        model_name = self._get_correct_model_name()
        
        # Models that do NOT support reasoning
        non_reasoning_models = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite"
        ]
        
        # Models that DO support reasoning
        reasoning_models = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite"
        ]
        
        if model_name in non_reasoning_models:
            return False
        elif model_name in reasoning_models:
            return True
        else:
            # Log warning for truly unknown models only
            # Preview versions are now mapped, so this should be rare
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown Gemini model '{model_name}' after mapping from '{self.model.name}' - assuming reasoning support")
            return True
    
    def _get_kwargs(self, kwargs: ModelKwargs | None):
        """
        Override to handle Gemini-specific parameters with reasoning_effort support.
        
        Maps reasoning_level to Google's reasoning_effort parameter.
        Maintains backward compatibility with thinking_budget.
        Only adds reasoning parameters for models that support them.
        """
        base_kwargs = super()._get_kwargs(kwargs)
        
        model_name = self._get_correct_model_name()
        supports_reasoning = self._model_supports_reasoning()
        
        if kwargs and supports_reasoning:
            reasoning_effort = self._map_reasoning_level_to_effort(kwargs)
            if reasoning_effort and reasoning_effort != "none":
                base_kwargs["reasoning_effort"] = reasoning_effort
        elif kwargs:
            reasoning_effort = self._map_reasoning_level_to_effort(kwargs)
            if reasoning_effort and reasoning_effort != "none":
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Model {model_name} does not support reasoning, ignoring reasoning_effort={reasoning_effort}")
        return base_kwargs
    
    def _map_reasoning_level_to_effort(self, kwargs: ModelKwargs) -> str:
        """
        Map reasoning_level or thinking_budget to Google's reasoning_effort parameter.
        
        Priority: reasoning_level (new) > thinking_budget (legacy) > "none" (default)
        """
        # Simple mapping for reasoning_level (preferred)
        REASONING_LEVEL_TO_EFFORT = {
            "disabled": "none",
            "low": "low",
            "medium": "medium", 
            "high": "high"
        }
        
        if kwargs.reasoning_level:
            return REASONING_LEVEL_TO_EFFORT.get(kwargs.reasoning_level, "none")
        
        # Legacy thinking_budget fallback
        if kwargs.thinking_budget is not None:
            if kwargs.thinking_budget == 0:
                return "none"
            elif kwargs.thinking_budget <= 512:
                return "low"
            elif kwargs.thinking_budget <= 1024:
                return "medium"
            else:
                return "high"
        
        return "none"
    
    async def get_response(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        """Override to use correct model name for API calls."""
        query = self.create_query_from_context(context=context)
        return await get_response_open_ai.get_response(
            client=self.client,
            model_name=self._get_correct_model_name(),  # Use mapped model name
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
            extra_headers=self.extra_headers,
        )

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        """Override to use correct model name for API calls."""
        query = self.create_query_from_context(context=context)
        tools = self._build_tools_from_context(context=context)
        return get_response_open_ai.get_response_streaming(
            client=self.client,
            model_name=self._get_correct_model_name(),  # Use mapped model name
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
            tools=tools,
            extra_headers=self.extra_headers,
        )