import json
from typing import AsyncGenerator

import litellm

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.logging.logging import LoggingDetails
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


class LiteLLMModelAdapter(CompletionModelAdapter):
    def __init__(self, model: CompletionModel):
        super().__init__(model)
        self.litellm_model = model.litellm_model_name
        
        logger.info(f"[LiteLLM] Initializing adapter for model: {model.name} -> {self.litellm_model}")
        
        # Set up Azure configuration if needed
        if self.litellm_model and self.litellm_model.startswith('azure/'):
            logger.info(f"[LiteLLM] Configuring Azure settings for {self.litellm_model}")
            litellm.api_key = get_settings().azure_api_key
            litellm.api_base = get_settings().azure_endpoint
            litellm.api_version = get_settings().azure_api_version
            logger.info(f"[LiteLLM] Azure config: base_url={get_settings().azure_endpoint}, version={get_settings().azure_api_version}")
        else:
            logger.info(f"[LiteLLM] No Azure configuration needed for {self.litellm_model}")

    def _get_kwargs(self, kwargs: ModelKwargs | None):
        if kwargs is None:
            logger.info(f"[LiteLLM] {self.litellm_model}: No kwargs provided")
            return {}
        
        # Get all kwargs from the model
        all_kwargs = kwargs.model_dump(exclude_none=True)
        logger.info(f"[LiteLLM] {self.litellm_model}: Raw kwargs from model: {all_kwargs}")
        
        # Try to get supported parameters for this specific model
        try:
            supported_params = litellm.get_supported_openai_params(model=self.litellm_model)
            logger.info(f"[LiteLLM] {self.litellm_model}: Supported parameters: {supported_params}")
            
            # Filter kwargs to only include supported parameters
            filtered_kwargs = {k: v for k, v in all_kwargs.items() if k in supported_params}
            
            if filtered_kwargs != all_kwargs:
                unsupported = set(all_kwargs.keys()) - set(filtered_kwargs.keys())
                logger.info(f"[LiteLLM] {self.litellm_model}: Filtered out unsupported parameters: {unsupported}")
            
            logger.info(f"[LiteLLM] {self.litellm_model}: Final filtered kwargs: {filtered_kwargs}")
            return filtered_kwargs
            
        except Exception as e:
            logger.warning(f"[LiteLLM] {self.litellm_model}: Could not get supported params: {e}")
            # Fallback: try to send all parameters and let LiteLLM/API handle validation
            # This ensures we don't accidentally block valid parameters due to discovery issues
            logger.info(f"[LiteLLM] {self.litellm_model}: Using all kwargs as fallback: {all_kwargs}")
            return all_kwargs

    def get_token_limit_of_model(self):
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION

    def get_logging_details(self, context: Context, model_kwargs: ModelKwargs):
        query = self.create_query_from_context(context=context)
        processed_kwargs = self._get_kwargs(model_kwargs)
        
        logger.info(f"[LiteLLM] {self.litellm_model}: Logging request with {len(query)} messages and processed kwargs: {processed_kwargs}")
        
        return LoggingDetails(
            json_body=json.dumps(query), model_kwargs=processed_kwargs
        )

    def create_query_from_context(self, context: Context):
        messages = []
        
        # Add system prompt if present
        if context.prompt:
            messages.append({"role": "system", "content": context.prompt})
        
        # Add conversation history
        for message in context.messages:
            # Add user message
            user_content = []
            user_content.append({"type": "text", "text": message.question})
            
            # Add images if present
            for image in message.images:
                if hasattr(image, 'base64_content') and image.base64_content:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image.base64_content}"
                        }
                    })
            
            messages.append({"role": "user", "content": user_content if len(user_content) > 1 else message.question})
            
            # Add assistant response
            messages.append({"role": "assistant", "content": message.answer})
        
        # Add current input
        current_content = []
        current_content.append({"type": "text", "text": context.input})
        
        # Add current images
        for image in context.images:
            if hasattr(image, 'base64_content') and image.base64_content:
                current_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image.base64_content}"
                    }
                })
        
        messages.append({"role": "user", "content": current_content if len(current_content) > 1 else context.input})
        
        return messages

    async def get_response(self, context: Context, model_kwargs: ModelKwargs | None = None):
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)
        
        logger.info(f"[LiteLLM] {self.litellm_model}: Making completion request with {len(messages)} messages and kwargs: {kwargs}")
        
        try:
            response = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                **kwargs
            )
            
            logger.info(f"[LiteLLM] {self.litellm_model}: Completion successful, response received")
            content = response.choices[0].message.content or ""
            return Completion(text=content, stop=True)
            
        except Exception as e:
            logger.error(f"[LiteLLM] {self.litellm_model}: Completion failed with error: {e}")
            logger.error(f"[LiteLLM] {self.litellm_model}: Failed request had kwargs: {kwargs}")
            raise

    def get_response_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None):
        return self._get_response_streaming(context, model_kwargs)

    async def _get_response_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None) -> AsyncGenerator[Completion, None]:
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)
        
        logger.info(f"[LiteLLM] {self.litellm_model}: Making streaming completion request with {len(messages)} messages and kwargs: {kwargs}")
        
        try:
            response = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=True,
                **kwargs
            )
            
            logger.info(f"[LiteLLM] {self.litellm_model}: Streaming completion started")
            
            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield Completion(text=delta.content)
                        
            # Send final stop chunk
            logger.info(f"[LiteLLM] {self.litellm_model}: Streaming completion finished")
            yield Completion(stop=True)
            
        except Exception as e:
            logger.error(f"[LiteLLM] {self.litellm_model}: Streaming completion failed with error: {e}")
            logger.error(f"[LiteLLM] {self.litellm_model}: Failed streaming request had kwargs: {kwargs}")
            raise