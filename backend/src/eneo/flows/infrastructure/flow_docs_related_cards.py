from __future__ import annotations

from dataclasses import dataclass
from html import escape

FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT = 'import { Cards } from "nextra/components";'


@dataclass(frozen=True, slots=True)
class FlowDocsNextraCard:
    title: str
    href: str


FlowDocsRelatedNextraCard = FlowDocsNextraCard


def render_flow_docs_related_nextra_cards(
    cards: tuple[FlowDocsNextraCard, ...],
) -> str:
    for card in cards:
        _validate_related_card(card)
    return _render_flow_docs_nextra_cards(cards)


def render_flow_docs_anchor_shortcut_cards(
    cards: tuple[FlowDocsNextraCard, ...],
) -> str:
    for card in cards:
        _validate_anchor_shortcut_card(card)
    hrefs = tuple(card.href for card in cards)
    if len(set(hrefs)) != len(hrefs):
        raise ValueError("Flow docs anchor shortcut card hrefs must be unique")
    return _render_flow_docs_nextra_cards(cards)


def _render_flow_docs_nextra_cards(cards: tuple[FlowDocsNextraCard, ...]) -> str:
    if not cards:
        raise ValueError("Flow docs Nextra cards require at least one card")

    column_count = min(len(cards), 3)
    lines = [f"<Cards num={{{column_count}}}>", ""]
    for card in cards:
        _validate_card_text(card)
        lines.extend(
            [
                "<Cards.Card",
                f'  title="{escape(card.title, quote=True)}"',
                f'  href="{escape(card.href, quote=True)}"',
                "  arrow",
                "/>",
                "",
            ]
        )
    lines.append("</Cards>")
    return "\n".join(lines)


def _validate_card_text(card: FlowDocsNextraCard) -> None:
    if not card.title.strip():
        raise ValueError("Flow docs Nextra card title must not be empty")
    if "\n" in card.title or "\n" in card.href:
        raise ValueError("Flow docs Nextra cards must not contain newlines")


def _validate_related_card(card: FlowDocsNextraCard) -> None:
    _validate_card_text(card)
    if not card.href.startswith("/"):
        raise ValueError("Flow docs related card href must be site-absolute")


def _validate_anchor_shortcut_card(card: FlowDocsNextraCard) -> None:
    _validate_card_text(card)
    if not card.href.startswith("#") or card.href == "#":
        raise ValueError("Flow docs anchor shortcut card href must be an anchor")
