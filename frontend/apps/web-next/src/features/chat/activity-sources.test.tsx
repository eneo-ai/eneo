// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SourceList } from "./activity-sources";
import { mergeSources } from "./message-parts";

afterEach(cleanup);

describe("source list", () => {
  it("distinguishes excerpts from the same document and opens the selected passage", async () => {
    const passages = [
      "Brasilianskt kaffe har chokladtoner.",
      "Det är ofta ett bra val för espresso.",
      "En mellanrostning ger balanserad sötma."
    ];
    const references: Schema<"McpToolReferencePublic">[] = passages.map((passage, chunk) => ({
      id: `reference-${chunk}`,
      uri: `eneo://info-blob/document-1#chunk-${chunk}`,
      content: `Title: kaffe_tips\ndocument_id: document-1\n\n${passage}`,
      meta: { title: "kaffe_tips", info_blob_id: "document-1" }
    }));
    const sources = mergeSources([], [], references).map((source) => ({
      ...source,
      origin: null,
      pageRange: null
    }));

    renderInApp(<SourceList messageId="answer-1" sources={sources} focusIndex={null} />);

    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    for (const [index, card] of cards.entries()) {
      expect(
        within(card).getByText(`Utdrag ${index + 1}`, { selector: "span:not(.sr-only)" })
      ).toBeTruthy();
      expect(within(card).getByText(passages[index]!, { selector: "span" })).toBeTruthy();
      expect(
        within(card).getByRole("button", { name: `kaffe_tips Utdrag ${index + 1}` })
      ).toBeTruthy();
    }
    await expectNoAxeViolations(document.body);

    const trigger = within(cards[1]!).getByRole("button", { name: "kaffe_tips Utdrag 2" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "kaffe_tips · Utdrag 2" });
    expect(within(dialog).getByText(passages[1]!)).toBeTruthy();
    expect(within(dialog).queryByText(/document_id:/)).toBeNull();
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Klar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});
