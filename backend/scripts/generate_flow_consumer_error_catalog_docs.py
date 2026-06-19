from __future__ import annotations

from flow_consumer_error_catalog_docs import (
    FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH,
    write_flow_consumer_error_reference_page,
)


def main() -> None:
    write_flow_consumer_error_reference_page()
    print(FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH)


if __name__ == "__main__":
    main()
