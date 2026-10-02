// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SectionedSettings } from "./sectioned-settings";

afterEach(cleanup);

const sections = [
  { id: "general", label: "Allmänt", icon: SlidersHorizontal, node: <h2>Allmänt</h2> },
  { id: "ai", label: "AI", icon: Sparkles, node: <h2>AI</h2> },
  {
    id: "security",
    label: "Säkerhet och integritet",
    icon: ShieldCheck,
    node: <h2>Säkerhet och integritet</h2>
  }
];

describe("SectionedSettings", () => {
  it("keeps navigation and content in the same section order and marks the selected anchor", () => {
    renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );

    const navigation = screen.getByRole("navigation", { name: "Avsnitt" });
    const links = within(navigation).getAllByRole("link");
    const generalLink = within(navigation).getByRole("link", { name: "Allmänt" });
    const aiLink = within(navigation).getByRole("link", { name: "AI" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "#general",
      "#ai",
      "#security"
    ]);
    expect(generalLink.getAttribute("aria-current")).toBe("true");
    expect(document.querySelectorAll("#general")).toHaveLength(1);
    expect(document.querySelectorAll("#ai")).toHaveLength(1);

    fireEvent.click(aiLink);
    expect(aiLink.getAttribute("aria-current")).toBe("true");
    expect(generalLink.hasAttribute("aria-current")).toBe(false);
  });

  it("is an Astryx tab strip: one tab stop, arrow keys, and overflow that scrolls with fades", () => {
    const { container } = renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );
    const navigation = screen.getByRole("navigation", { name: "Avsnitt" });
    const current = within(navigation).getByRole("link", { name: "Allmänt" });
    const others = within(navigation)
      .getAllByRole("link")
      .filter((link) => link !== current);
    expect(current.getAttribute("tabindex")).toBe("0");
    expect(others.every((link) => link.getAttribute("tabindex") === "-1")).toBe(true);

    current.focus();
    fireEvent.keyDown(current, { key: "ArrowRight" });
    expect(document.activeElement).toBe(within(navigation).getByRole("link", { name: "AI" }));

    // Astryx's scrolling strip (edge fades, current tab kept in view), so a
    // long label is never truncated: it keeps its full accessible name.
    expect(container.querySelector(".astryx-tab-strip")).toBeTruthy();
    expect(within(navigation).getByRole("link", { name: "Säkerhet och integritet" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );
    await expectNoAxeViolations(container);
  });
});
