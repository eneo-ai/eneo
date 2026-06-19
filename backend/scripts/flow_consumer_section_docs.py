from __future__ import annotations

from flow_consumer_guide_support import (
    FLOW_API_GUIDE_HREF,
    FLOW_CONSUMER_ERROR_REFERENCE_HREF,
    FLOW_CONSUMER_SECTION_NAV,
    GuidePage,
    output_path_for,
    render_markdown_table,
    render_page,
    validate_consumer_section_nav,
    write_page,
)

FLOW_CONSUMER_SECTION_INDEX_OUTPUT_PATH = output_path_for("index")


def validate_flow_consumer_section_catalog() -> None:
    validate_consumer_section_nav(FLOW_CONSUMER_SECTION_NAV)


def render_flow_consumer_section_index_page() -> str:
    validate_flow_consumer_section_catalog()
    journey_rows = tuple(
        (entry.title, entry.job, f"[Open]({entry.href})")
        for entry in FLOW_CONSUMER_SECTION_NAV
        if entry.slug != "index"
    )
    body = (
        "## Journey map",
        "",
        render_markdown_table(("Page", "Use it for", "Link"), journey_rows),
        "",
        "## Reference owners",
        "",
        f"- [Flows API Guide]({FLOW_API_GUIDE_HREF}) owns the full runtime API field catalog.",
        f"- [Flow error reference]({FLOW_CONSUMER_ERROR_REFERENCE_HREF}) owns machine-readable error handling.",
        "- The pages in this section link to those references instead of duplicating request and response shapes.",
    )
    return render_page(
        GuidePage(
            slug="index",
            title="Eneo Flows for API consumers",
            purpose="This section is for teams that use Eneo Flows inside their own service or web app, and it helps you choose the right guide before you design, run, or troubleshoot a flow.",
            orientation="You are at the start of the consumer journey: design the flow, integrate the runtime calls, then use the FAQ and reference when questions come up.",
            body=body,
        )
    )


def write_flow_consumer_section_index_page() -> None:
    write_page(
        FLOW_CONSUMER_SECTION_INDEX_OUTPUT_PATH,
        render_flow_consumer_section_index_page(),
    )


if __name__ == "__main__":
    write_flow_consumer_section_index_page()
