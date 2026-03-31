from __future__ import annotations

from pathlib import Path


def test_ddd_flow_modules_are_no_longer_compatibility_stubs() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "intric" / "flows"
    targets = [
        root / "application" / "flow_service.py",
        root / "application" / "flow_run_service.py",
        root / "application" / "flow_dispatch.py",
        root / "infrastructure" / "flow_repo.py",
        root / "infrastructure" / "flow_run_repo.py",
        root / "infrastructure" / "flow_version_repo.py",
        root / "domain" / "flow.py",
    ]

    for path in targets:
        text = path.read_text()
        assert "Compatibility re-export" not in text, path.name
