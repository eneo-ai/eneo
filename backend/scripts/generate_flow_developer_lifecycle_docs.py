from __future__ import annotations

from flow_developer_lifecycle_docs import (
    FLOW_DEVELOPER_LIFECYCLE_DOCS_OUTPUT_PATH,
    write_flow_developer_lifecycle_docs_page,
)


def main() -> None:
    write_flow_developer_lifecycle_docs_page()
    print(FLOW_DEVELOPER_LIFECYCLE_DOCS_OUTPUT_PATH)


if __name__ == "__main__":
    main()
