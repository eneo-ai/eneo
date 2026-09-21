from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FileExtractionLimits(BaseSettings):
    """Per-process policy for background document extraction."""

    model_config = SettingsConfigDict(env_prefix="FILE_EXTRACTION_", frozen=True)

    concurrency: int = Field(default=2, gt=0, le=32)
    timeout_seconds: float = Field(default=60, gt=0)
    cpu_seconds: int = Field(default=30, gt=0)
    memory_bytes: int = Field(default=1_073_741_824, ge=67_108_864)
    max_output_bytes: int = Field(default=10_000_000, gt=0)
    max_archive_bytes: int = Field(default=134_217_728, gt=0)
    max_archive_entries: int = Field(default=10_000, gt=0)
    max_pdf_pages: int = Field(default=1_000, gt=0)


@lru_cache(maxsize=1)
def get_file_extraction_limits() -> FileExtractionLimits:
    return FileExtractionLimits()
