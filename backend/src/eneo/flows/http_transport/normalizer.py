from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport.authored_config import HttpAuthoredConfig
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.validator import authored_url_error
from eneo.main.exceptions import TypedIOValidationException


def is_authored_config(raw: Mapping[str, object] | None) -> bool:
    """Return whether the payload declares the authored HTTP config shape."""
    return isinstance(raw, Mapping) and "auth" in raw


def parse_authored_http_config(
    raw_config: object, *, step_order: int, config_label: str
) -> HttpAuthoredConfig:
    """Parse a stored HTTP config, as the runtime does before it sends from it.

    This is the one acceptance of a stored config: the request compiler, the
    webhook delivery, the run preflight and the save checks all parse with it,
    so a config the runtime would reject is rejected everywhere with the same
    typed code. That includes the URL defects known before the request (a fixed
    URL that is not absolute http(s), userinfo even behind a template). The
    error names the field, never the value.
    """
    if not isinstance(raw_config, Mapping):
        raise _invalid_config(
            f"Step {step_order}: {config_label} must be an authored HTTP config object.",
            field=config_label,
        )
    raw_config = cast(Mapping[str, object], raw_config)
    if not is_authored_config(raw_config):
        raise _invalid_config(
            f"Step {step_order}: {config_label} must use authored HTTP config with an "
            "auth field; legacy flat HTTP config is no longer supported.",
            field=config_label,
        )
    try:
        authored = HttpAuthoredConfig.model_validate(raw_config)
    except ValidationError as exc:
        # Pydantic's message quotes the input value; only the location goes on.
        location = ".".join(str(part) for part in exc.errors()[0]["loc"])
        field = f"{config_label}.{location}" if location else config_label
        raise _invalid_config(
            f"Step {step_order}: {field} is not a valid HTTP config value.",
            field=field,
        ) from None
    url_error = authored_url_error(authored.url)
    if url_error is not None:
        raise _invalid_config(
            url_error_message(
                step_order=step_order, config_label=config_label, url_error=url_error
            ),
            field=f"{config_label}.url",
        )
    return authored


def url_error_message(
    *, step_order: int, config_label: str, url_error: HttpTransportError
) -> str:
    problem = (
        "is required"
        if url_error is HttpTransportError.MISSING_URL
        else "is not an absolute http or https URL without userinfo"
    )
    return f"Step {step_order}: {config_label}.url {problem} ({url_error.value})."


def _invalid_config(message: str, *, field: str) -> TypedIOValidationException:
    return TypedIOValidationException(
        message,
        code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        context={"field": field},
    )
