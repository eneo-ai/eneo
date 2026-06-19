from __future__ import annotations

from intric.flows.infrastructure.flow_schema_docs_exporter import (
    FLOW_DEVELOPER_SCHEMA_DOCS_OUTPUT_PATH,
    write_flow_schema_docs_page,
)


def main() -> None:
    write_flow_schema_docs_page()
    print(FLOW_DEVELOPER_SCHEMA_DOCS_OUTPUT_PATH)


if __name__ == "__main__":
    main()
