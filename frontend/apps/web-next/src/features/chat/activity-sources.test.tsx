// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SourceList } from "./activity-sources";
import { mergeSources } from "./message-parts";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.GET.mockReset();
});

/** A knowledge document the answer cites, as the stream and the history give it. */
function documentSources(url: string | null = null) {
  return mergeSources([
    {
      type: "source-document",
      sourceId: "blob-1",
      mediaType: "text/plain",
      title: "Upphandlingspolicy.pdf",
      providerMetadata: {
        eneo: { id: "blob-1", metadata: { title: "Upphandlingspolicy.pdf", url } }
      }
    }
  ]).map((source) => ({ ...source, origin: "Upphandling", pageRange: null }));
}

describe("source list", () => {
  it.each([true, false])(
    "opens a cited knowledge document's text, with its original only when kept: %s",
    async (originalAvailable) => {
      api.GET.mockResolvedValue({
        data: { text: "Gränsen är 700 000 kr.", original_available: originalAvailable },
        response: new Response("{}")
      });
      renderInApp(<SourceList messageId="answer-doc" sources={documentSources()} />);
      const trigger = screen.getByRole("button", { name: "Upphandlingspolicy.pdf" });
      trigger.focus();
      fireEvent.click(trigger);

      const dialog = await screen.findByRole("dialog", { name: "Upphandlingspolicy.pdf" });
      expect(await within(dialog).findByText("Gränsen är 700 000 kr.")).toBeTruthy();
      expect(api.GET).toHaveBeenCalledWith(
        "/api/v1/info-blobs/{id}/",
        expect.objectContaining({ params: { path: { id: "blob-1" } } })
      );
      expect(
        within(dialog).getByRole("button", { name: "Ladda ner extraherad text" })
      ).toBeTruthy();
      expect(within(dialog).queryByRole("button", { name: "Ladda ner original" }) !== null).toBe(
        originalAvailable
      );
      await expectNoAxeViolations(dialog);

      fireEvent.click(within(dialog).getAllByRole("button", { name: "Stäng" })[0]!);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(trigger));
    }
  );

  it("links a cited document with a web address to it instead", () => {
    renderInApp(
      <SourceList messageId="answer-doc" sources={documentSources("https://example.com/p")} />
    );
    expect(screen.getByRole("link", { name: /Upphandlingspolicy\.pdf/ }).getAttribute("href")).toBe(
      "https://example.com/p"
    );
    expect(screen.queryByRole("button", { name: "Upphandlingspolicy.pdf" })).toBeNull();
  });

  it.each(["crawl-page", "web-search"])(
    "opens an MCP %s source as an external link",
    async (sourceType) => {
      const sources = mergeSources(
        [],
        [],
        [
          {
            id: "web-1",
            uri: "https://example.com/source",
            content: "Source passage",
            meta: { sourceType, title: "Web source" }
          }
        ]
      ).map((source) => ({ ...source, origin: null, pageRange: null }));
      renderInApp(<SourceList messageId="answer-web" sources={sources} />);
      const link = screen.getByRole("link", { name: /Web source/ });
      expect(link.getAttribute("href")).toBe("https://example.com/source");
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noreferrer");
      await expectNoAxeViolations(document.body);
    }
  );

  it("keeps an unsafe MCP web-search URI as a snippet without a navigable link", async () => {
    const sources = mergeSources(
      [],
      [],
      [
        {
          id: "web-unsafe",
          uri: "javascript:alert(1)",
          content: "Source passage",
          meta: { sourceType: "web-search", title: "Web source" }
        }
      ]
    ).map((source) => ({ ...source, origin: null, pageRange: null }));
    renderInApp(<SourceList messageId="answer-web" sources={sources} />);
    expect(screen.queryByRole("link")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Web source" }));
    const dialog = await screen.findByRole("dialog", { name: "Web source" });
    expect(within(dialog).getByText("Source passage")).toBeTruthy();
    expect(within(dialog).queryByRole("link")).toBeNull();
  });

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

    renderInApp(<SourceList messageId="answer-1" sources={sources} />);

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
