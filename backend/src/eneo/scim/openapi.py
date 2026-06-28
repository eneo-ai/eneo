from http import HTTPStatus
from typing import Any


def scim_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {"description": HTTPStatus(status_code).phrase}
        for status_code in status_codes
    }
