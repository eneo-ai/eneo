from datetime import datetime

from pydantic import BaseModel, Field

# Release identifiers mirror the versions in frontend/packages/whats-new/releases.json:
# plain semver without a leading "v" (e.g. "2.2.0", "2.3.0-rc.1").
RELEASE_VERSION_PATTERN = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"


class WhatsNewSeenUpdate(BaseModel):
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=RELEASE_VERSION_PATTERN,
        description="The newest release the user has opened on the What's new page.",
        examples=["2.2.0"],
    )


class WhatsNewSeenPublic(BaseModel):
    version: str | None = Field(
        description="Newest release the user has seen, or null when they never opened the page.",
    )
    seen_at: datetime | None = None
