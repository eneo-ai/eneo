from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eneo.files.file_models import FileType
from eneo.json_types import JsonObject


class FlowRunStepInputFileMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    name: str
    checksum: str
    size: int
    mimetype: str | None
    file_type: FileType
    text_size_bytes: int | None
    has_text: bool
    has_transcription: bool

    def to_runtime_input_file_payload(self) -> JsonObject:
        return {
            "id": str(self.file_id),
            "name": self.name,
            "checksum": self.checksum,
            "size": self.size,
            "mimetype": self.mimetype,
            "file_type": self.file_type.value,
            "text_size_bytes": self.text_size_bytes,
            "has_text": self.has_text,
            "has_transcription": self.has_transcription,
        }
