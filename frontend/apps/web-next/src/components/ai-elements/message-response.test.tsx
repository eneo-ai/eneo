// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useMemo } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { resolveInrefs } from "@/lib/chat/inref";
import {
  CitationSourcesProvider,
  citationComponents,
  citationNumber,
  remarkCitations
} from "./citation";
import { answerHeadingLevel } from "./markdown-components";
import { MessageResponse } from "./message";

afterEach(cleanup);

const SOURCES = [
  { title: "Upphandlingspolicy 2024", url: "https://intranat.kommun.se/policy" },
  { title: "LOU 19 kap." }
];
const SOURCE_IDS = ["a5477f85-1111", "b3291cc0-2222"];

const ANSWER = [
  "## Sammanfattning",
  "",
  'Gränsen stämmer med tröskelvärdet<inref id="a5477f85"/>, men efterannonsering saknas<inref id="b3291cc0"/>.',
  "",
  "| Kommun | Avvikelse |",
  "| --- | --- |",
  "| Sundsvall | Hög |",
  "| Umeå | Medel |",
  "",
  "1. Lägg till krav på efterannonsering.",
  "2. Inför stickprov.",
  "",
  "```json",
  '{ "gräns": 700000 }',
  "```"
].join("\n");

function Answer({
  text,
  onOpenSource
}: {
  text: string;
  onOpenSource: (index: number, trigger: HTMLElement) => void;
}) {
  // Memoized like the chat does, so blocks are not re-parsed every render.
  const remarkPlugins = useMemo(() => [remarkCitations(SOURCES.length, "msg-1")], []);
  return (
    <CitationSourcesProvider value={SOURCES} prefix="msg-1" onOpenSource={onOpenSource}>
      <MessageResponse remarkPlugins={remarkPlugins} components={citationComponents}>
        {resolveInrefs(text, SOURCE_IDS)}
      </MessageResponse>
    </CitationSourcesProvider>
  );
}

function renderAnswer(
  onOpenSource: (index: number, trigger: HTMLElement) => void = vi.fn(),
  text = ANSWER
) {
  return renderInApp(<Answer text={text} onOpenSource={onOpenSource} />);
}

describe("MessageResponse", () => {
  // Regression: passing remarkPlugins replaced Streamdown's defaults (GFM), so
  // tables rendered as raw `| a | b |` text.
  it("renders GFM tables as real tables while citations still resolve", () => {
    const { container } = renderAnswer();

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(container.textContent).not.toContain("| Kommun |");
    const headers = within(table!).getAllByRole("columnheader");
    expect(headers.map((th) => th.textContent)).toEqual(["Kommun", "Avvikelse"]);
    for (const th of headers) expect(th.getAttribute("scope")).toBe("col");
    expect(within(table!).getAllByRole("row")).toHaveLength(3);

    // Chips open the source in the activity panel: buttons, not dead in-page links.
    const first = screen.getByRole("button", { name: "Källa 1: Upphandlingspolicy 2024" });
    expect(first.textContent).toBe("1");
    expect(first.hasAttribute("href")).toBe(false);
    expect(screen.getByRole("button", { name: "Källa 2: LOU 19 kap." })).toBeTruthy();
  });

  it("puts tables and code blocks in named scroll regions", async () => {
    renderAnswer();
    // Astryx ScrollableArea: a named region that joins the tab order only when
    // the table overflows (jsdom has no layout, so it never does here).
    const tableRegion = screen.getByRole("region", { name: "Tabell" });
    expect(tableRegion.querySelector("table")).not.toBeNull();
    expect(tableRegion.hasAttribute("tabindex")).toBe(false);

    const codeRegion = await screen.findByRole("region", { name: "Kodblock (json)" });
    expect(codeRegion.getAttribute("tabindex")).toBe("0");
    expect(codeRegion.textContent).toContain("700000");
    expect(screen.getByRole("button", { name: "Kopiera kod" })).toBeTruthy();
  });

  it("keeps list numbering and starts answer headings at h3", () => {
    const { container } = renderAnswer();
    const list = container.querySelector("ol");
    expect(list?.className).toContain("list-decimal");
    expect(list?.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByRole("heading", { level: 3, name: "Sammanfattning" })).toBeTruthy();
    expect(answerHeadingLevel(1)).toBe(3);
    expect(answerHeadingLevel(3)).toBe(4);
    expect(answerHeadingLevel(6)).toBe(6);
  });

  it("opens the cited source", () => {
    const onOpenSource = vi.fn();
    renderAnswer(onOpenSource);
    const chip = screen.getByRole("button", { name: "Källa 2: LOU 19 kap." });
    fireEvent.click(chip);
    expect(onOpenSource).toHaveBeenCalledWith(1, chip);
  });

  it("leaves raw numeric brackets plain while rendering a validated inref as a chip", () => {
    const { container } = renderAnswer(
      vi.fn(),
      'Literal [1] and [3]. Cited<inref id="a5477f85"/>.'
    );
    expect(container.textContent).toContain("Literal [1] and [3].");
    const chips = screen.getAllByRole("button", { name: /^Källa \d+:/ });
    expect(chips).toHaveLength(1);
    expect(chips[0]?.textContent).toBe("1");
  });

  it("shows an out-of-range private marker as plain text", () => {
    const { container } = renderAnswer(vi.fn(), "Out of range \uE0003\uE001.");
    expect(container.textContent).toContain("Out of range [3].");
    expect(screen.queryByRole("button", { name: /^Källa \d+:/ })).toBeNull();
  });

  // Links outside this message's numbered sources remain ordinary links.
  it("keeps other links plain, even when they look like citation markers", () => {
    renderAnswer(
      vi.fn(),
      [
        "Se [policyn](https://evil.example/lou-cite-1),",
        "[ett annat svar](#msg-2-cite-1) och [en saknad källa](#msg-1-cite-9)."
      ].join(" ")
    );
    expect(screen.queryByRole("button", { name: /^Källa/ })).toBeNull();
    const external = screen.getByRole("link", { name: "policyn" });
    expect(external.getAttribute("href")).toBe("https://evil.example/lou-cite-1");
    expect(external.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("ett annat svar")).toBeTruthy();
    expect(screen.getByText("en saknad källa")).toBeTruthy();
  });

  it("matches only this message's markers within its sources", () => {
    expect(citationNumber("#msg-1-cite-2", "msg-1", 2)).toBe(2);
    expect(citationNumber("#msg-1-cite-3", "msg-1", 2)).toBeNull();
    expect(citationNumber("#msg-1-cite-0", "msg-1", 2)).toBeNull();
    expect(citationNumber("#msg-2-cite-1", "msg-1", 2)).toBeNull();
    expect(citationNumber("https://x.se/#msg-1-cite-1", "msg-1", 2)).toBeNull();
    expect(citationNumber("#msg-1-cite-1x", "msg-1", 2)).toBeNull();
    expect(citationNumber(undefined, "msg-1", 2)).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderAnswer();
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Kodblock (json)" })).toBeTruthy()
    );
    await expectNoAxeViolations(container);
  });
});
