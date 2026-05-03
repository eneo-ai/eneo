from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

ArchitectureErrorCode = Literal[
    "architecture_materialization_failed",
    "architecture_critic_invariant_failed",
]
ArchitectureLogValue = str | int | bool | None


class AIBuilderArchitectureError(Exception):
    def __init__(
        self,
        *,
        public_code: ArchitectureErrorCode,
        detail: str,
        log_context: Mapping[str, ArchitectureLogValue] | None = None,
    ) -> None:
        super().__init__(detail)
        self.public_code = public_code
        self.detail = detail
        self.log_context: Mapping[str, ArchitectureLogValue] = MappingProxyType(
            dict(log_context or {})
        )

    def log_extra(self) -> dict[str, ArchitectureLogValue]:
        return {
            "architecture_error_code": self.public_code,
            "architecture_error_detail": self.detail,
            **self.log_context,
        }
