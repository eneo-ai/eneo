from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from eneo.flows.runtime.document_rendering.blocks import (
    DocumentBlock,
    InlineRuns,
    InlineTextRun,
)

_MARKDOWN = (
    MarkdownIt("commonmark").enable("table").enable("strikethrough").disable("lheading")
)


def parse_markdown_blocks(lines: list[str]) -> list[DocumentBlock]:
    if not lines:
        return [DocumentBlock(kind="paragraph", text="")]

    tokens = _MARKDOWN.parse("\n".join(lines))
    blocks: list[DocumentBlock] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token.type == "heading_open":
            block, index = _consume_heading(tokens, index)
            blocks.append(block)
            continue

        if token.type == "paragraph_open":
            block, index = _consume_paragraph(tokens, index)
            if block.text:
                blocks.append(block)
            continue

        if token.type == "bullet_list_open":
            block, index = _consume_list(tokens, index, ordered=False)
            if block.items:
                blocks.append(block)
            continue

        if token.type == "ordered_list_open":
            block, index = _consume_list(tokens, index, ordered=True)
            if block.items:
                blocks.append(block)
            continue

        if token.type in {"fence", "code_block"}:
            blocks.append(DocumentBlock(kind="code", text=token.content.rstrip("\n")))
            index += 1
            continue

        if token.type == "table_open":
            block, index = _consume_table(tokens, index)
            if block.rows:
                blocks.append(block)
            continue

        if token.type == "hr":
            blocks.append(DocumentBlock(kind="empty"))
            index += 1
            continue

        if token.type == "html_block" and token.content.strip():
            blocks.append(DocumentBlock(kind="paragraph", text=token.content.strip()))

        index += 1

    return blocks or [DocumentBlock(kind="paragraph", text="")]


def _consume_heading(
    tokens: Sequence[Token],
    start_index: int,
) -> tuple[DocumentBlock, int]:
    token = tokens[start_index]
    level = _heading_level(token)
    inline = _first_inline_until(tokens, start_index + 1, "heading_close")
    runs = _inline_runs(inline)
    next_index = _index_after_closing_token(tokens, start_index, "heading_close")
    return (
        DocumentBlock(
            kind="heading",
            text=_runs_text(runs),
            level=level,
            runs=runs,
        ),
        next_index,
    )


def _heading_level(token: Token) -> int:
    if token.tag.startswith("h") and token.tag[1:].isdigit():
        return min(max(int(token.tag[1:]), 1), 4)
    return 1


def _consume_paragraph(
    tokens: Sequence[Token],
    start_index: int,
) -> tuple[DocumentBlock, int]:
    inline = _first_inline_until(tokens, start_index + 1, "paragraph_close")
    runs = _inline_runs(inline)
    next_index = _index_after_closing_token(tokens, start_index, "paragraph_close")
    return (
        DocumentBlock(kind="paragraph", text=_runs_text(runs), runs=runs),
        next_index,
    )


def _consume_list(
    tokens: Sequence[Token],
    start_index: int,
    *,
    ordered: bool,
) -> tuple[DocumentBlock, int]:
    open_type = tokens[start_index].type
    close_type = "ordered_list_close" if ordered else "bullet_list_close"
    items: list[str] = []
    item_run_groups: list[InlineRuns] = []
    depth = 1
    index = start_index + 1

    while index < len(tokens):
        token = tokens[index]
        if token.type == open_type:
            depth += 1
        elif token.type == close_type:
            depth -= 1
            if depth == 0:
                return (
                    DocumentBlock(
                        kind="numbered_list" if ordered else "bullet_list",
                        items=tuple(items),
                        item_runs=tuple(item_run_groups),
                    ),
                    index + 1,
                )
        elif depth == 1 and token.type == "list_item_open":
            item_runs, index = _consume_list_item(tokens, index)
            item_text = _runs_text(item_runs)
            if item_text:
                items.append(item_text)
                item_run_groups.append(item_runs)
            continue
        index += 1

    return (
        DocumentBlock(
            kind="numbered_list" if ordered else "bullet_list",
            items=tuple(items),
            item_runs=tuple(item_run_groups),
        ),
        index,
    )


def _consume_list_item(
    tokens: Sequence[Token],
    start_index: int,
) -> tuple[InlineRuns, int]:
    depth = 1
    runs: list[InlineTextRun] = []
    index = start_index + 1

    while index < len(tokens):
        token = tokens[index]
        if token.type == "list_item_open":
            depth += 1
        elif token.type == "list_item_close":
            depth -= 1
            if depth == 0:
                return tuple(runs), index + 1
        elif token.type == "inline":
            inline_runs = _inline_runs(token)
            if runs and inline_runs:
                runs.append(InlineTextRun(" "))
            runs.extend(inline_runs)
        elif token.type in {"fence", "code_block"} and token.content.strip():
            if runs:
                runs.append(InlineTextRun(" "))
            runs.append(InlineTextRun(token.content.strip(), code=True))
        index += 1

    return tuple(runs), index


def _consume_table(
    tokens: Sequence[Token],
    start_index: int,
) -> tuple[DocumentBlock, int]:
    rows: list[tuple[str, ...]] = []
    row_runs: list[tuple[InlineRuns, ...]] = []
    current_row: list[str] = []
    current_row_runs: list[InlineRuns] = []
    in_cell = False
    depth = 1
    index = start_index + 1

    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            depth += 1
        elif token.type == "table_close":
            depth -= 1
            if depth == 0:
                return (
                    DocumentBlock(
                        kind="table",
                        rows=tuple(rows),
                        row_runs=tuple(row_runs),
                    ),
                    index + 1,
                )
        elif token.type == "tr_open":
            current_row = []
            current_row_runs = []
        elif token.type == "tr_close":
            rows.append(tuple(current_row))
            row_runs.append(tuple(current_row_runs))
        elif token.type in {"th_open", "td_open"}:
            in_cell = True
        elif token.type in {"th_close", "td_close"}:
            in_cell = False
        elif in_cell and token.type == "inline":
            runs = _inline_runs(token)
            current_row.append(_runs_text(runs))
            current_row_runs.append(runs)
        index += 1

    return (
        DocumentBlock(kind="table", rows=tuple(rows), row_runs=tuple(row_runs)),
        index,
    )


def _first_inline_until(
    tokens: Sequence[Token],
    start_index: int,
    close_type: str,
) -> Token | None:
    index = start_index
    while index < len(tokens) and tokens[index].type != close_type:
        if tokens[index].type == "inline":
            return tokens[index]
        index += 1
    return None


def _index_after_closing_token(
    tokens: Sequence[Token],
    start_index: int,
    close_type: str,
) -> int:
    index = start_index + 1
    while index < len(tokens):
        if tokens[index].type == close_type:
            return index + 1
        index += 1
    return index


def _inline_runs(token: Token | None) -> InlineRuns:
    if token is None:
        return ()
    children = token.children or []
    if not children:
        return (InlineTextRun(token.content.strip()),) if token.content.strip() else ()

    runs: list[InlineTextRun] = []
    state = _InlineState()
    for child in children:
        if child.type in {"strong_open", "em_open", "s_open"}:
            state = state.enter(child.type)
        elif child.type in {"strong_close", "em_close", "s_close"}:
            state = state.exit(child.type)
        elif child.type in {"text", "html_inline"}:
            if child.content:
                runs.append(state.run(child.content))
        elif child.type == "code_inline":
            if child.content:
                runs.append(state.run(child.content, code=True))
        elif child.type in {"softbreak", "hardbreak"}:
            runs.append(InlineTextRun("\n"))
        elif child.type == "image":
            if child.content:
                runs.append(state.run(child.content))
    return _trim_runs(tuple(runs))


def _runs_text(runs: InlineRuns) -> str:
    return "".join(run.text for run in runs).strip()


def _trim_runs(runs: InlineRuns) -> InlineRuns:
    if not runs:
        return ()
    mutable = list(runs)
    first = mutable[0]
    mutable[0] = InlineTextRun(
        first.text.lstrip(),
        bold=first.bold,
        italic=first.italic,
        code=first.code,
        strikethrough=first.strikethrough,
    )
    last = mutable[-1]
    mutable[-1] = InlineTextRun(
        last.text.rstrip(),
        bold=last.bold,
        italic=last.italic,
        code=last.code,
        strikethrough=last.strikethrough,
    )
    return tuple(run for run in mutable if run.text)


@dataclass(frozen=True)
class _InlineState:
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False

    def enter(self, token_type: str) -> _InlineState:
        return self._with_token(token_type, enabled=True)

    def exit(self, token_type: str) -> _InlineState:
        return self._with_token(token_type, enabled=False)

    def run(self, text: str, *, code: bool = False) -> InlineTextRun:
        return InlineTextRun(
            text,
            bold=self.bold,
            italic=self.italic,
            code=code,
            strikethrough=self.strikethrough,
        )

    def _with_token(self, token_type: str, *, enabled: bool) -> _InlineState:
        if token_type.startswith("strong_"):
            return _InlineState(
                bold=enabled,
                italic=self.italic,
                strikethrough=self.strikethrough,
            )
        if token_type.startswith("em_"):
            return _InlineState(
                bold=self.bold,
                italic=enabled,
                strikethrough=self.strikethrough,
            )
        if token_type.startswith("s_"):
            return _InlineState(
                bold=self.bold,
                italic=self.italic,
                strikethrough=enabled,
            )
        return self
