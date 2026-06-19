from __future__ import annotations

from flow_consumer_designing_flows_docs import (
    FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH as DESIGNING_OUTPUT_PATH,
)
from flow_consumer_designing_flows_docs import (
    write_flow_consumer_guide_page as write_designing_page,
)
from flow_consumer_faq_docs import (
    FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH as FAQ_OUTPUT_PATH,
)
from flow_consumer_faq_docs import (
    write_flow_consumer_guide_page as write_faq_page,
)
from flow_consumer_integrating_flows_docs import (
    FLOW_CONSUMER_GUIDE_DOCS_OUTPUT_PATH as INTEGRATING_OUTPUT_PATH,
)
from flow_consumer_integrating_flows_docs import (
    write_flow_consumer_guide_page as write_integrating_page,
)
from flow_consumer_section_docs import (
    FLOW_CONSUMER_SECTION_INDEX_OUTPUT_PATH as SECTION_INDEX_OUTPUT_PATH,
)
from flow_consumer_section_docs import (
    write_flow_consumer_section_index_page as write_section_index_page,
)


def main() -> None:
    write_section_index_page()
    write_designing_page()
    write_integrating_page()
    write_faq_page()
    for output_path in (
        SECTION_INDEX_OUTPUT_PATH,
        DESIGNING_OUTPUT_PATH,
        INTEGRATING_OUTPUT_PATH,
        FAQ_OUTPUT_PATH,
    ):
        print(output_path)


if __name__ == "__main__":
    main()
