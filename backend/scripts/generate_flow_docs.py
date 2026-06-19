from __future__ import annotations

from collections.abc import Callable

from generate_flow_consumer_error_catalog_docs import (
    main as generate_flow_consumer_error_catalog_docs,
)
from generate_flow_consumer_guide_docs import main as generate_flow_consumer_guide_docs
from generate_flow_developer_architecture_docs import (
    main as generate_flow_developer_architecture_docs,
)
from generate_flow_developer_error_taxonomy_docs import (
    main as generate_flow_developer_error_taxonomy_docs,
)
from generate_flow_developer_key_decisions_docs import (
    main as generate_flow_developer_key_decisions_docs,
)
from generate_flow_developer_lifecycle_docs import (
    main as generate_flow_developer_lifecycle_docs,
)
from generate_flow_developer_reviewer_guide_docs import (
    main as generate_flow_developer_reviewer_guide_docs,
)
from generate_flow_developer_schema_docs import (
    main as generate_flow_developer_schema_docs,
)

FLOW_DOCS_GENERATORS: tuple[Callable[[], None], ...] = (
    generate_flow_consumer_guide_docs,
    generate_flow_consumer_error_catalog_docs,
    generate_flow_developer_architecture_docs,
    generate_flow_developer_schema_docs,
    generate_flow_developer_lifecycle_docs,
    generate_flow_developer_error_taxonomy_docs,
    generate_flow_developer_key_decisions_docs,
    generate_flow_developer_reviewer_guide_docs,
)


def main() -> None:
    for generate_docs in FLOW_DOCS_GENERATORS:
        generate_docs()


if __name__ == "__main__":
    main()
