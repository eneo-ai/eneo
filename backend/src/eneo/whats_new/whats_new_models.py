from pydantic import BaseModel, Field

# Release identifiers mirror the versions in frontend/packages/whats-new/releases.json:
# plain semver without a leading "v" (e.g. "2.2.0", "2.3.0-rc.1").
RELEASE_VERSION_PATTERN = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"


class WhatsNewVersionUpdate(BaseModel):
    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=RELEASE_VERSION_PATTERN,
        description="A release id as written in releases.json.",
        examples=["2.2.0"],
    )


class WhatsNewStatePublic(BaseModel):
    seen_version: str | None = Field(
        description="Newest release the user has opened the What's new page for; null before the first visit.",
    )
    announced_version: str | None = Field(
        description="Newest release the user has been shown the announcement for; null before the first one.",
    )


def release_order_key(
    version: str,
) -> tuple[int, int, int, int, tuple[tuple[int, object], ...]]:
    """Semver order for release ids; a pre-release sorts before its final."""
    core, _, pre = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in pre.split(".")
        if part
    )
    return (major, minor, patch, 0 if identifiers else 1, identifiers)
