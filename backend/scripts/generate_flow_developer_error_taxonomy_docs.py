from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from intric.flows.api.flow_api_error_metadata import (  # noqa: E402
    render_flow_error_taxonomy_docs_page,
)

FLOW_DEVELOPER_ERROR_TAXONOMY_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "when-things-fail.mdx"
)


def main() -> None:
    FLOW_DEVELOPER_ERROR_TAXONOMY_DOCS_OUTPUT_PATH.write_text(
        render_flow_error_taxonomy_docs_page(),
        encoding="utf-8",
    )
    print(FLOW_DEVELOPER_ERROR_TAXONOMY_DOCS_OUTPUT_PATH)


if __name__ == "__main__":
    main()
