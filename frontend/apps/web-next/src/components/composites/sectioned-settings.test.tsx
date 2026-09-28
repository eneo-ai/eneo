// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { SlidersHorizontal, Sparkles } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { SectionedSettings } from "./sectioned-settings";

afterEach(cleanup);

describe("SectionedSettings", () => {
  it("keeps navigation and content in the same section order and marks the selected anchor", () => {
    render(
      <SectionedSettings
        navigationLabel="Inställningar"
        header={<h1>Redigera</h1>}
        sections={[
          { id: "general", label: "Allmänt", icon: SlidersHorizontal, node: <h2>Allmänt</h2> },
          { id: "ai", label: "AI", icon: Sparkles, node: <h2>AI</h2> }
        ]}
      />
    );

    const navigation = screen.getByRole("navigation", { name: "Inställningar" });
    const links = within(navigation).getAllByRole("link");
    const generalLink = within(navigation).getByRole("link", { name: "Allmänt" });
    const aiLink = within(navigation).getByRole("link", { name: "AI" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["#general", "#ai"]);
    expect(generalLink.getAttribute("aria-current")).toBe("location");
    expect(document.querySelectorAll("#general")).toHaveLength(1);
    expect(document.querySelectorAll("#ai")).toHaveLength(1);

    fireEvent.click(aiLink);
    expect(aiLink.getAttribute("aria-current")).toBe("location");
    expect(generalLink.hasAttribute("aria-current")).toBe(false);
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <SectionedSettings
        navigationLabel="Inställningar"
        header={<h1>Redigera</h1>}
        sections={[
          { id: "general", label: "Allmänt", icon: SlidersHorizontal, node: <h2>Allmänt</h2> }
        ]}
      />
    );
    await expectNoAxeViolations(container);
  });
});
