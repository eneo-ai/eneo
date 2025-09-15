# LiteLLM Provider Configuration

This module handles custom provider configurations for LiteLLM integration within the Eneo platform.

## Overview

The LiteLLM provider system allows you to integrate AI model providers that are either:
1. **Not natively supported** by LiteLLM
2. **Need custom configuration** (API endpoints, authentication, model transformations)

For providers that are natively supported by LiteLLM (OpenAI, Azure, Claude, Mistral, etc.), no custom provider class is needed.

## Architecture

### Core Components

- **`BaseLiteLLMProvider`**: Base class that provides default behavior for standard LiteLLM providers
- **`LiteLLMProviderRegistry`**: Central registry that manages all provider configurations
- **Provider Classes**: Custom provider implementations (e.g., `BergetProvider`)

### How It Works

1. Each AI model has a `litellm_model_name` field that determines which provider to use
2. Models with custom providers use a `litellm_model_name` with a provider prefix (e.g., `berget/model-name`)
3. The registry detects the provider from the prefix and returns appropriate configuration
4. The LiteLLM adapters use the provider to configure API calls

## When to Add a Custom Provider

Create a custom provider class **only if**:

- ✅ The provider is NOT natively supported by LiteLLM
- ✅ The provider needs custom API configuration (base URL, headers, etc.)
- ✅ The provider requires model name transformation

## Natively Supported Providers (No Custom Class Needed)

These work automatically with the base provider:
- OpenAI (`openai`)
- Azure OpenAI (`azure`) 
- Anthropic/Claude (`claude`)
- Mistral (`mistral`)
- Google (`gemini`)
- And [many others](https://docs.litellm.ai/docs/providers) - check LiteLLM docs

## Adding a Custom Provider

### Step 1: Create Provider Class

Create a new file in this directory (e.g., `my_provider.py`):

```python
import os
from typing import Dict, Any
from .base_provider import BaseLiteLLMProvider

class MyProvider(BaseLiteLLMProvider):
    \"\"\"Configuration for My AI Provider\"\"\"
    
    def get_model_prefix(self) -> str:
        return "myprovider/"
    
    def get_litellm_model(self, model_name: str) -> str:
        # Transform model name for LiteLLM routing
        if model_name.startswith(self.get_model_prefix()):
            return model_name.replace(self.get_model_prefix(), "openai/")
        return f"openai/{model_name}"
    
    def get_api_config(self) -> Dict[str, Any]:
        return {
            'api_base': os.getenv("MY_PROVIDER_API_BASE"),
            'api_key': os.getenv("MY_PROVIDER_API_KEY"),
        }
    
    def get_env_vars(self) -> Dict[str, str]:
        return {
            'api_key': 'MY_PROVIDER_API_KEY',
            'api_base': 'MY_PROVIDER_API_BASE',
        }
```

### Step 2: Add to Registry

Update `provider_registry.py` to detect your provider prefix:

```python
from .my_provider import MyProvider

class LiteLLMProviderRegistry:
    @classmethod
    def get_provider_for_model(cls, family: ModelFamily, litellm_model_name: Optional[str]) -> BaseLiteLLMProvider:
        # Check for your provider prefix
        if litellm_model_name and litellm_model_name.startswith("myprovider/"):
            return MyProvider()
        
        # Check for Berget models
        if litellm_model_name and litellm_model_name.startswith("berget/"):
            return BergetProvider()
        
        return cls._default_provider
```

### Step 3: Configure Models

Use existing model families with your provider prefix:

```yaml
completion_models:
  - name: 'my-model-provider'
    family: 'openai'  # Use existing family that matches the API type
    litellm_model_name: 'myprovider/my-model'
    org: MyProvider  # For UI grouping
    # ... other config
```

### Step 4: Environment Variables

Set required environment variables:

```bash
MY_PROVIDER_API_KEY=your-api-key
MY_PROVIDER_API_BASE=https://api.myprovider.com/v1
```

## Example: Berget Provider

The `BergetProvider` demonstrates integrating an OpenAI-compatible API:

```python
class BergetProvider(BaseLiteLLMProvider):
    def get_model_prefix(self) -> str:
        return "berget/"
    
    def get_litellm_model(self, model_name: str) -> str:
        # Route through OpenAI-compatible endpoint
        if model_name.startswith("berget/"):
            return model_name.replace("berget/", "openai/")
        return f"openai/{model_name}"
    
    def get_api_config(self) -> Dict[str, Any]:
        return {
            'api_base': os.getenv("BERGET_API_BASE", "https://api.berget.ai/v1"),
            'api_key': os.getenv("BERGET_API_KEY"),
        }
```

Usage in `ai_models.yml`:
```yaml
- name: 'multilingual-e5-large-berget'
  family: 'e5'  # Use the API type, not the provider
  litellm_model_name: 'berget/intfloat/multilingual-e5-large-instruct'
  org: Berget  # For UI grouping
  # LiteLLM will call openai/intfloat/multilingual-e5-large-instruct with Berget's API config
```

## Model Compatibility System

For embedding models, the system supports cross-provider compatibility. See `embedding_models/domain/model_compatibility.py` for details.

This allows collections created with one provider (e.g., OpenAI) to work with the same model from another provider (e.g., Berget), as long as they're marked as compatible.

## Testing Your Provider

1. Set environment variables
2. Add test models to `ai_models.yml`
3. Create a simple completion/embedding request
4. Check logs for provider configuration messages

## Best Practices

- **Keep it simple**: Only override methods you need to customize
- **Use environment variables**: Don't hardcode API keys or URLs
- **Follow naming conventions**: Use clear, descriptive provider names
- **Document requirements**: Note any special setup or limitations
- **Test thoroughly**: Verify both completion and embedding models work

## Troubleshooting

Common issues:
- **Missing environment variables**: Check your `.env` file
- **Wrong model prefix**: Ensure `litellm_model_name` matches your provider logic
- **API compatibility**: Verify the provider's API is truly OpenAI-compatible
- **Authentication**: Check if provider requires special headers or auth format