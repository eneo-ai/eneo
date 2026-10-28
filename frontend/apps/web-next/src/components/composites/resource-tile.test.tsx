// @vitest-environment jsdom
import { act, cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ResourceCard, ResourceCollection } from "./resource-tile";

afterEach(cleanup);

function Collection() {
  return (
    <ResourceCollection>
      <ResourceCard
        href="/spaces/s1/apps/a1"
        name="Protokollsammanfattning"
        tile={<span aria-hidden="true">P</span>}
        description="Sammanfattar protokoll."
        meta={["JSON"]}
        actions={<button type="button">Fler åtgärder för Protokollsammanfattning</button>}
      />
      <ResourceCard
        href="/spaces/s1/apps/a2"
        name="Avtalsanalys"
        tile={<span aria-hidden="true">A</span>}
      />
    </ResourceCollection>
  );
}

describe("ResourceCollection (decision 9)", () => {
  it("lists the resources as rows on a phone, each row one link with its menu beside it", async () => {
    setViewport("phone");
    const { container } = renderInApp(<Collection />);
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    const link = within(items[0]!).getByRole("link", { name: /^Protokollsammanfattning/ });
    expect(link.getAttribute("href")).toBe("/spaces/s1/apps/a1");
    // What the row says is read with it; the menu is its own control.
    expect(link.textContent).toContain("Sammanfattar protokoll.");
    expect(link.textContent).toContain("JSON");
    expect(within(items[0]!).getByRole("button", { name: /^Fler åtgärder/ })).toBeTruthy();
    expect(link.contains(within(items[0]!).getByRole("button"))).toBe(false);
    expect(items[0]!.className).toContain("astryx-item");
    await expectNoAxeViolations(container);
  });

  it("shows cards from a tablet up, as many columns as the room takes", () => {
    setViewport("tablet-portrait");
    renderInApp(<Collection />);
    // The first list is the grid; a card's tokens are a list of their own.
    const grid = screen.getAllByRole("list")[0]!;
    expect(grid.className).toContain("auto-fill");
    expect(screen.getByRole("link", { name: "Protokollsammanfattning" })).toBeTruthy();
  });

  it("ends a row whose menu has nothing the user may do with a chevron", () => {
    setViewport("phone");
    const NoActions = () => null;
    renderInApp(
      <ResourceCollection>
        <ResourceCard
          href="/spaces/s1/apps/a1"
          name="Läsbar"
          tile={<span aria-hidden="true">L</span>}
          actions={<NoActions />}
        />
      </ResourceCollection>
    );
    const row = screen.getByRole("listitem");
    const menuSlot = row.querySelector(".peer")!;
    // CSS shows the chevron while the menu's slot is empty (peer-empty).
    expect(menuSlot.childNodes).toHaveLength(0);
    expect(menuSlot.nextElementSibling?.getAttribute("class")).toContain("peer-empty:block");
  });

  it("gives the focus to the same resource when a turned phone swaps rows for cards", () => {
    setViewport("phone");
    renderInApp(<Collection />);
    act(() => screen.getByRole("button", { name: /^Fler åtgärder/ }).focus());

    act(() => setViewport("tablet-portrait"));
    expect(document.activeElement?.getAttribute("href")).toBe("/spaces/s1/apps/a1");
  });
});
