from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from intric.main.exceptions import NameCollisionException
from intric.model_providers.domain.model_provider import ModelProvider
from intric.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from intric.settings.encryption_service import EncryptionService

if TYPE_CHECKING:
    pass


class ModelProviderService:
    """Service for managing model providers with credential encryption."""

    def __init__(self, repository: ModelProviderRepository, encryption: EncryptionService):
        self.repository = repository
        self.encryption = encryption

    def _encrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Encrypt sensitive credential fields."""
        encrypted_creds = credentials.copy()

        # Encrypt API key if present
        if "api_key" in encrypted_creds and encrypted_creds["api_key"]:
            encrypted_creds["api_key"] = self.encryption.encrypt(encrypted_creds["api_key"])

        # Add more credential fields here if needed in the future
        # e.g., client_secret, access_token, etc.

        return encrypted_creds

    def _decrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Decrypt sensitive credential fields."""
        decrypted_creds = credentials.copy()

        # Decrypt API key if present
        if "api_key" in decrypted_creds and decrypted_creds["api_key"]:
            decrypted_creds["api_key"] = self.encryption.decrypt(decrypted_creds["api_key"])

        return decrypted_creds

    async def get_all(self, active_only: bool = False) -> list[ModelProvider]:
        """Get all providers for the tenant."""
        return await self.repository.all(active_only=active_only)

    async def get_by_id(self, provider_id: UUID) -> ModelProvider:
        """Get a provider by ID."""
        return await self.repository.get_by_id(provider_id)

    async def create(
        self,
        tenant_id: UUID,
        name: str,
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
        is_active: bool = True,
    ) -> ModelProvider:
        """Create a new provider."""
        # Check for duplicate names
        existing = await self.repository.get_by_name(name)
        if existing is not None:
            raise NameCollisionException(f"Provider with name '{name}' already exists")

        # Encrypt credentials before storing
        encrypted_credentials = self._encrypt_credentials(credentials)

        # Create domain entity
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        provider = ModelProvider(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            provider_type=provider_type,
            credentials=encrypted_credentials,
            config=config,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

        return await self.repository.create(provider)

    async def update(
        self,
        provider_id: UUID,
        name: Optional[str] = None,
        provider_type: Optional[str] = None,
        credentials: Optional[dict[str, Any]] = None,
        config: Optional[dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> ModelProvider:
        """Update an existing provider."""
        # Get existing provider
        provider = await self.repository.get_by_id(provider_id)

        # Check for duplicate names if name is being changed
        if name is not None and name != provider.name:
            existing = await self.repository.get_by_name(name)
            if existing is not None:
                raise NameCollisionException(f"Provider with name '{name}' already exists")
            provider.name = name

        # Update fields if provided
        if provider_type is not None:
            provider.provider_type = provider_type

        if credentials is not None:
            provider.credentials = self._encrypt_credentials(credentials)

        if config is not None:
            provider.config = config

        if is_active is not None:
            provider.is_active = is_active

        return await self.repository.update(provider)

    async def delete(self, provider_id: UUID) -> None:
        """Delete a provider.

        Raises:
            ValueError: If the provider has models attached to it
        """
        # Check if provider has any models
        model_count = await self.repository.count_models_for_provider(provider_id)
        if model_count > 0:
            raise ValueError(
                f"Cannot delete provider: {model_count} model(s) are using this provider. "
                "Delete the models first."
            )

        await self.repository.delete(provider_id)

    async def get_decrypted_credentials(self, provider_id: UUID) -> dict[str, Any]:
        """Get decrypted credentials for a provider (for internal use only)."""
        provider = await self.repository.get_by_id(provider_id)
        return self._decrypt_credentials(provider.credentials)

    async def validate_model(
        self, provider_id: UUID, model_name: str, model_type: str
    ) -> dict[str, Any]:
        """Validate a model by making a minimal LiteLLM call.

        For completion models: sends a single-token completion request.
        For embedding models: sends a minimal embedding request.
        For transcription models: skips validation (requires audio file).
        """
        if model_type == "transcription":
            return {"success": True, "message": "Validation skipped for transcription models"}

        import litellm

        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")
        provider_type = provider.provider_type.lower()

        # Build the litellm model identifier
        # For vLLM, use hosted_vllm prefix for litellm compliance
        if provider_type == "vllm":
            litellm_model = f"hosted_vllm/{model_name}"
        elif provider_type == "azure":
            litellm_model = f"azure/{model_name}"
        else:
            litellm_model = f"{provider_type}/{model_name}"

        kwargs: dict[str, Any] = {"model": litellm_model, "api_key": api_key}

        # Add provider-specific config
        if provider_type == "azure":
            kwargs["api_base"] = provider.config.get("endpoint", "")
            kwargs["api_version"] = provider.config.get(
                "api_version", "2024-02-15-preview"
            )
        elif provider_type in ("vllm",) or provider.config.get("endpoint"):
            kwargs["api_base"] = provider.config.get("endpoint", "")

        try:
            if model_type == "embedding":
                await litellm.aembedding(input=["test"], **kwargs)
            else:
                await litellm.acompletion(
                    messages=[{"role": "user", "content": "hi"}],
                    max_completion_tokens=1,
                    drop_params=True,
                    **kwargs,
                )
            return {"success": True, "message": "Model validated successfully"}
        except litellm.AuthenticationError:
            return {"success": False, "error": "Invalid API key"}
        except litellm.NotFoundError:
            return {"success": False, "error": f"Model not found: {model_name}"}
        except litellm.APIConnectionError:
            return {"success": False, "error": "Could not connect to API"}
        except Exception as e:
            return {"success": False, "error": f"Validation failed: {str(e)}"}

    async def list_available_models(self, provider_id: UUID) -> list[dict[str, Any]]:
        """List models/deployments available on a provider using its credentials."""
        import httpx

        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")
        provider_type = provider.provider_type.lower()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if provider_type == "azure":
                    # Azure /openai/models returns all available models in the
                    # region, not just deployed ones. Skip live listing — users
                    # should enter their deployment name manually.
                    return []

                elif provider_type == "openai":
                    resp = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return [
                        {"name": m["id"], "owned_by": m.get("owned_by", "")}
                        for m in sorted(data.get("data", []), key=lambda m: m["id"])
                    ]

                elif provider_type == "anthropic":
                    resp = await client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return [
                        {"name": m["id"], "display_name": m.get("display_name", "")}
                        for m in sorted(data.get("data", []), key=lambda m: m["id"])
                    ]

                else:
                    # For other providers, try OpenAI-compatible /v1/models
                    endpoint = provider.config.get("endpoint", "").rstrip("/")
                    if endpoint:
                        resp = await client.get(
                            f"{endpoint}/v1/models",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        return [
                            {"name": m["id"]}
                            for m in sorted(
                                data.get("data", []), key=lambda m: m["id"]
                            )
                        ]
                    return []

        except Exception as e:
            return [{"error": f"Failed to list models: {str(e)}"}]

    async def test_connection(self, provider_id: UUID) -> dict[str, Any]:
        """Test connectivity to a model provider by making a minimal LiteLLM call.

        Tries multiple test models per provider as fallback in case older models
        have been deprecated.
        """
        import litellm

        provider = await self.repository.get_by_id(provider_id)
        decrypted_creds = self._decrypt_credentials(provider.credentials)
        api_key = decrypted_creds.get("api_key", "")

        provider_type = provider.provider_type.lower()
        base_kwargs: dict[str, Any] = {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "api_key": api_key,
        }

        # Multiple candidates per provider, ordered from cheapest/newest to oldest.
        # If a model is retired, the next one in the list is tried.
        test_model_candidates: dict[str, list[str]] = {
            "openai": [
                "openai/gpt-4o-mini",
                "openai/gpt-4.1-nano",
                "openai/gpt-3.5-turbo",
            ],
            "anthropic": [
                "anthropic/claude-3-5-haiku-20241022",
                "anthropic/claude-3-haiku-20240307",
                "anthropic/claude-3-5-sonnet-20241022",
            ],
            "gemini": [
                "gemini/gemini-2.0-flash",
                "gemini/gemini-1.5-flash",
                "gemini/gemini-pro",
            ],
            "cohere": [
                "cohere/command-r",
                "cohere/command-r-plus",
                "cohere/command",
            ],
            "mistral": [
                "mistral/mistral-small-latest",
                "mistral/mistral-tiny",
                "mistral/open-mistral-7b",
            ],
        }

        # Azure and vLLM use provider config, not a candidate list
        if provider_type == "azure":
            deployment = provider.config.get("deployment_name", "gpt-4o-mini")
            base_kwargs["model"] = f"azure/{deployment}"
            base_kwargs["api_base"] = provider.config.get("endpoint", "")
            base_kwargs["api_version"] = provider.config.get(
                "api_version", "2024-02-15-preview"
            )
            candidates = [base_kwargs["model"]]
        elif provider_type == "vllm":
            base_kwargs["api_base"] = provider.config.get("endpoint", "")
            candidates = ["openai/test"]
        elif provider_type in test_model_candidates:
            candidates = test_model_candidates[provider_type]
        else:
            model_name = provider.config.get("model_name", "test")
            if provider.config.get("endpoint"):
                base_kwargs["api_base"] = provider.config["endpoint"]
            candidates = [f"openai/{model_name}"]

        for model in candidates:
            kwargs = {**base_kwargs, "model": model}
            try:
                await litellm.acompletion(**kwargs)
                return {"success": True, "message": "Connection successful"}
            except litellm.AuthenticationError:
                return {"success": False, "error": "Invalid API key"}
            except litellm.APIConnectionError:
                return {"success": False, "error": "Could not connect to the API"}
            except litellm.NotFoundError:
                # Model not found — try next candidate
                continue
            except Exception as e:
                # For non-model errors, no point retrying with a different model
                return {"success": False, "error": f"Connection test failed: {str(e)}"}

        # All candidates returned NotFound
        return {
            "success": False,
            "error": (
                "None of the test models could be found. "
                "The provider may not support completion models, "
                "or the API endpoint may be misconfigured."
            ),
        }
