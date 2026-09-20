from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.domain.step_output import FileBackedStepText


class TextProcessingMode(StrEnum):
    PROCESS_EACH_SECTION = "process_each_section"


class TextProcessingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: TextProcessingMode


def text_processing_config(
    input_config: dict[str, Any] | None,
) -> TextProcessingConfig | None:
    value = (input_config or {}).get("text_processing")
    return TextProcessingConfig.model_validate(value) if value is not None else None


class SectionRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_char: int = Field(strict=True, ge=0)
    end_char: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> SectionRange:
        if self.end_char <= self.start_char:
            raise ValueError("Section ranges must be nonempty and ordered.")
        return self


class TextSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    core: SectionRange
    context: tuple[SectionRange, ...] = ()
    output_index: int = Field(strict=True, ge=0)


class SectionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    utf8_length: int = Field(strict=True, gt=0)
    character_length: int = Field(strict=True, gt=0)
    sources: tuple[FileBackedStepText, ...] = ()
    sections: tuple[TextSection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coverage(self) -> SectionManifest:
        end = 0
        for index, section in enumerate(self.sections):
            if section.core.start_char != end:
                raise ValueError("Section core coverage must have no gaps or overlap.")
            end = section.core.end_char
            if section.output_index != index:
                raise ValueError("Section output_index must match its ordered record.")
            if any(span.end_char > self.character_length for span in section.context):
                raise ValueError("Section context exceeds the complete text.")
        if end != self.character_length:
            raise ValueError("Section core coverage must cover the complete text.")
        return self

    def resplit(self, text: str) -> tuple[str, ...]:
        if len(text) != self.character_length:
            raise ValueError(
                "Section manifest character length does not match the text."
            )
        content = text.encode("utf-8")
        if len(content) != self.utf8_length:
            raise ValueError("Section manifest UTF-8 length does not match the text.")
        if sha256(content).hexdigest() != self.content_sha256:
            raise ValueError("Section manifest content hash does not match the text.")
        parts = tuple(
            text[section.core.start_char : section.core.end_char]
            for section in self.sections
        )
        if "".join(parts) != text:
            raise ValueError("Section ranges do not reproduce the complete text.")
        return parts
