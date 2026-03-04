"""Canonical input/output type policies for flows."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InputTypePolicy:
    channel: str  # "text_only" | "files_only"
    contract_allowed: bool  # can input_contract be set?
    requires_extraction: bool  # must raw extraction produce non-empty text?
    requires_files: bool  # must have at least one valid file?
    supported: bool = True


INPUT_TYPE_POLICIES: dict[str, InputTypePolicy] = {
    "text": InputTypePolicy(
        channel="text_only", contract_allowed=True, requires_extraction=False, requires_files=False
    ),
    "json": InputTypePolicy(
        channel="text_only", contract_allowed=True, requires_extraction=False, requires_files=False
    ),
    "document": InputTypePolicy(
        channel="text_only", contract_allowed=False, requires_extraction=True, requires_files=False
    ),
    "image": InputTypePolicy(
        channel="files_only",
        contract_allowed=False,
        requires_extraction=False,
        requires_files=True,
        supported=False,
    ),
    "file": InputTypePolicy(
        channel="text_only", contract_allowed=False, requires_extraction=True, requires_files=False
    ),
    "audio": InputTypePolicy(
        channel="text_only",
        contract_allowed=False,
        requires_extraction=False,
        requires_files=False,
        supported=True,
    ),
    "any": InputTypePolicy(
        channel="text_only", contract_allowed=False, requires_extraction=False, requires_files=False
    ),
}
