from __future__ import annotations

from typing import Final

FLOW_DOCS_MERMAID_FIGURE_CLASS: Final[str] = "flow-docs-mermaid-figure"
# The docs-site stylesheet owns the figure surface; this helper owns the
# generated wrapper and Mermaid init directive.
FLOW_DOCS_MERMAID_FIGURE_OPEN: Final[str] = (
    f'<div className="{FLOW_DOCS_MERMAID_FIGURE_CLASS}">'
)
FLOW_DOCS_MERMAID_INIT_DIRECTIVE: Final[str] = (
    '%%{init: {"themeVariables": {'
    '"background": "#f8f6f0", '
    '"primaryColor": "#e8ded1", '
    '"primaryTextColor": "#242620", '
    '"primaryBorderColor": "#6f7b5d", '
    '"secondaryColor": "#d7e0d2", '
    '"tertiaryColor": "#f1ece4", '
    '"lineColor": "#78816f", '
    '"edgeLabelBackground": "#f8f6f0", '
    '"clusterBkg": "#f4efe7", '
    '"clusterBorder": "#9a8a73", '
    '"fontFamily": "Inter, ui-sans-serif, system-ui, sans-serif"'
    "}}}%%"
)


def render_flow_docs_mermaid_block(*lines: str) -> str:
    for line in lines:
        if "```" in line:
            raise ValueError("Flow Mermaid body lines must not contain code fences")

    return "\n".join(
        (
            FLOW_DOCS_MERMAID_FIGURE_OPEN,
            "",
            "```mermaid",
            FLOW_DOCS_MERMAID_INIT_DIRECTIVE,
            *lines,
            "```",
            "",
            "</div>",
        )
    )
