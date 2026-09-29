"""Purpose-based configuration shared by spaces, assistants and policy."""

from typing import Literal

from pydantic import BaseModel

CapabilityPurpose = Literal[
    "web_search",
    "image_generation",
    "tabular_analysis",
    "document_creation",
    "spreadsheet_creation",
]


class CapabilityAvailability(BaseModel):
    purpose: CapabilityPurpose
    available: bool
    reason: str | None = None
