// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useMemo } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatTestProviders } from "@/features/chat/testing";
import { expectNoAxeViolations } from "@/test/axe";
import { CitationSourcesProvider, citationComponents, remarkCitations } from "./citation";
import { answerHeadingLevel } from "./markdown-components";
import { MessageResponse } from "./message";

afterEach(cleanup);

const SOURCES = [
  { title: "Upphandlingspolicy 2024", url: "https://intranat.kommun.se/policy" },
  { title: "LOU 19 kap." }
];

const ANSWER = [
  "## Sammanfattning",
  "",
  "Gränsen stämmer med tröskelvärdet[1], men efterannonsering saknas[2].",
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
  onOpenSource
}: {
  onOpenSource?: (index: number, trigger: HTMLElement) => void;
}) {
  // Memoized like the chat does, so blocks are not re-parsed every render.
  const remarkPlugins = useMemo(() => [remarkCitations(SOURCES.length, "msg-1")], []);
  return (
    <CitationSourcesProvider value={SOURCES} onOpenSource={onOpenSource}>
      <MessageResponse remarkPlugins={remarkPlugins} components={citationComponents}>
        {ANSWER}
      </MessageResponse>
    </CitationSourcesProvider>
  );
}

function renderAnswer(onOpenSource?: (index: number, trigger: HTMLElement) => void) {
  return render(
    <ChatTestProviders>
      <Answer onOpenSource={onOpenSource} />
    </ChatTestProviders>
  );
}

describe("MessageResponse", () => {
  // Regression: passing remarkPlugins replaced Streamdown's defaults (GFM), so
  // tables rendered as raw `| a | b |` text.
  it("renders GFM tables as real tables while citation links still resolve", () => {
    const { container } = renderAnswer();

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(container.textContent).not.toContain("| Kommun |");
    const headers = within(table!).getAllByRole("columnheader");
    expect(headers.map((th) => th.textContent)).toEqual(["Kommun", "Avvikelse"]);
    for (const th of headers) expect(th.getAttribute("scope")).toBe("col");
    expect(within(table!).getAllByRole("row")).toHaveLength(3);

    const first = screen.getByRole("link", { name: "Källa 1: Upphandlingspolicy 2024" });
    expect(first.getAttribute("href")).toBe("#msg-1-cite-1");
    expect(screen.getByRole("link", { name: "Källa 2: LOU 19 kap." })).toBeTruthy();
  });

  it("puts wide tables and code blocks in named, keyboard-scrollable regions", async () => {
    renderAnswer();
    const tableRegion = screen.getByRole("region", { name: "Tabell" });
    expect(tableRegion.getAttribute("tabindex")).toBe("0");
    expect(tableRegion.querySelector("table")).not.toBeNull();

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

  it("opens the cited source instead of following the in-page link", () => {
    const onOpenSource = vi.fn();
    renderAnswer(onOpenSource);
    const link = screen.getByRole("link", { name: "Källa 2: LOU 19 kap." });
    fireEvent.click(link);
    expect(onOpenSource).toHaveBeenCalledWith(1, link);
  });

  it("has no axe violations", async () => {
    const { container } = renderAnswer();
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Kodblock (json)" })).toBeTruthy()
    );
    await expectNoAxeViolations(container);
  });
});
