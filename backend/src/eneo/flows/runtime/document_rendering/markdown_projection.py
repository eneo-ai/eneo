"""Project flow-owned document structure into the shared renderer's Markdown."""

import re
from collections.abc import Sequence

from eneo.flows.runtime.document_rendering.blocks import DocumentBlock, InlineRuns


def _literal(text: str) -> str:
    # Structured values are data: characters such as * must survive as text.
    return re.sub(r"([\\`*_{}\[\]<>()#!|~+\-.])", r"\\\1", text)


def _inline(text: str, runs: InlineRuns = ()) -> str:
    if not runs:
        return _literal(text)
    output: list[str] = []
    for run in runs:
        value = _literal(run.text)
        if run.code:
            fence = "`" * (
                max((len(m[0]) for m in re.finditer(r"`+", run.text)), default=0) + 1
            )
            value = f"{fence} {run.text} {fence}"
        if run.bold:
            value = f"**{value}**"
        if run.italic:
            value = f"*{value}*"
        if run.strikethrough:
            value = f"~~{value}~~"
        if run.href:
            target = (
                run.href.replace("\\", "%5C")
                .replace("(", "%28")
                .replace(")", "%29")
                .replace(" ", "%20")
            )
            value = f"[{value}]({target})"
        output.append(value)
    return "".join(output)


def blocks_to_markdown(blocks: Sequence[DocumentBlock]) -> str:
    output: list[str] = []
    for block in blocks:
        if block.kind == "empty":
            continue
        if block.kind == "heading":
            output.append("#" * block.level + " " + _inline(block.text, block.runs))
        elif block.kind in {"bullet_list", "numbered_list"}:
            items: list[str] = []
            counters: dict[int, int] = {}
            previous_level = 0
            for i, text in enumerate(block.items):
                level = block.item_level(i)
                if level < previous_level:
                    counters = {
                        depth: count
                        for depth, count in counters.items()
                        if depth <= level
                    }
                if level > previous_level:
                    counters[level] = 0
                counters[level] = (
                    counters.get(level, block.start - 1 if level == 0 else 0) + 1
                )
                previous_level = level
                prefix = "- " if block.kind == "bullet_list" else f"{counters[level]}. "
                runs = block.item_runs[i] if i < len(block.item_runs) else ()
                lines = _inline(text, runs).splitlines() or [""]
                indent = "    " * block.item_level(i)
                items.append(
                    indent
                    + prefix
                    + lines[0]
                    + "".join(
                        "\n" + indent + " " * len(prefix) + line for line in lines[1:]
                    )
                )
            output.append("\n".join(items))
        elif block.kind == "table":
            rows: list[str] = []
            for i, row in enumerate(block.rows):
                runs = block.row_runs[i] if i < len(block.row_runs) else ()
                cells = [
                    _inline(cell, runs[j] if j < len(runs) else ()).replace(
                        "\n", "<br>"
                    )
                    for j, cell in enumerate(row)
                ]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                rows.insert(1, "| " + " | ".join("---" for _ in block.rows[0]) + " |")
            output.append("\n".join(rows))
        elif block.kind == "code":
            fence = "`" * max(
                3,
                max((len(m[0]) for m in re.finditer(r"`+", block.text)), default=0) + 1,
            )
            output.append(fence + "\n" + block.text + "\n" + fence)
        else:
            output.append(_inline(block.text, block.runs))
    return "\n\n".join(output)
