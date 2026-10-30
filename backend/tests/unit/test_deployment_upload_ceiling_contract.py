"""Shipped configuration must not reintroduce an environment upload policy."""

from pathlib import Path


def test_shipped_templates_leave_upload_limits_to_admin_policy() -> None:
    root = Path(__file__).resolve().parents[3]
    for path in (
        root / "docs/deployment/env_backend.template",
        root / "backend/.env.template",
    ):
        assert not any(
            line.startswith("OBJECT_CONTENT_INLINE_MAXIMUM_BYTES=")
            for line in path.read_text().splitlines()
        )
