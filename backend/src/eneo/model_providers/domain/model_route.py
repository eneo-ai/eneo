MAX_MODEL_ROUTE_LENGTH = 1024


def resolve_model_route(
    *,
    model_name: str,
    provider_type: str | None = None,
    litellm_model_name: str | None = None,
) -> str:
    """Return the provider-qualified route used for LiteLLM operations."""
    if provider_type:
        route = f"{provider_type}/{model_name}"
    else:
        route = litellm_model_name or model_name
    if len(route) > MAX_MODEL_ROUTE_LENGTH:
        raise ValueError(
            f"Model route cannot exceed {MAX_MODEL_ROUTE_LENGTH} characters"
        )
    return route
