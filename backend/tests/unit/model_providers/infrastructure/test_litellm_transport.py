"""Rejected-parameter detection across the error shapes image calls produce."""

import pytest
from litellm.exceptions import BadRequestError, UnsupportedParamsError

from eneo.model_providers.infrastructure.litellm_transport import unsupported_param


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            UnsupportedParamsError(
                status_code=500,
                message="Setting `response_format` is not supported by openai, x.",
            ),
            "response_format",
        ),
        (
            UnsupportedParamsError(
                status_code=500,
                message=(
                    "The following parameters are not supported for model "
                    "gpt-image-1: quality, response_format"
                ),
            ),
            "quality",
        ),
        (
            BadRequestError(
                message="Unknown parameter: 'quality'.",
                model="dall-e-2",
                llm_provider="openai",
            ),
            "quality",
        ),
        (
            BadRequestError(
                message="Invalid image format.", model="x", llm_provider="openai"
            ),
            None,
        ),
        (RuntimeError("Setting `n` is not supported"), None),
    ],
)
def test_unsupported_param_names_the_rejected_parameter(exc, expected):
    assert unsupported_param(exc) == expected


def test_unsupported_param_follows_the_exception_chain():
    cause = UnsupportedParamsError(
        status_code=500, message="Setting `size` is not supported by x, y."
    )
    wrapped = RuntimeError("wrapped")
    wrapped.__cause__ = cause
    assert unsupported_param(wrapped) == "size"
