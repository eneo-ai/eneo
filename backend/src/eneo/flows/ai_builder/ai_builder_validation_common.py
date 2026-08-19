from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.ai_builder.ai_builder_domain_models import (
    LintSeverity,
    LintWarning,
)


@dataclass(frozen=True)
class SpecValidationError:
    step_ref: str | None
    code: str
    message: str


class SpecValidationResult:
    def __init__(self) -> None:
        self.errors: list[SpecValidationError] = []
        self.warnings: list[LintWarning] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, *, step_ref: str | None, code: str, message: str) -> None:
        self.errors.append(
            SpecValidationError(step_ref=step_ref, code=code, message=message)
        )

    def add_warning(
        self,
        *,
        step_ref: str | None,
        code: str,
        message: str,
        severity: LintSeverity = LintSeverity.WARNING,
    ) -> None:
        self.warnings.append(
            LintWarning(
                step_ref=step_ref, code=code, message=message, severity=severity
            )
        )
