// @vitest-environment jsdom
import { act, cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ResourceCard, ResourceCollection } from "./resource-tile";

afterEach(cleanup);

function Collection({ desktopList }: { desktopList?: React.ReactNode } = {}) {
  return (
    <ResourceCollection desktopList={desktopList}>
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

  it("puts the tokens beside the status only where no description has that place", () => {
    setViewport("phone");
    const row = (description?: string) => (
      <ResourceCard
        href="/spaces/s1/apps/a1"
        name="Bygglov"
        tile={<span aria-hidden="true">B</span>}
        status={<span>Publicerad</span>}
        description={description}
        meta={["GPT-5"]}
      />
    );
    const line = (text: string) => screen.getByText(text).parentElement;

    renderInApp(<ResourceCollection>{row()}</ResourceCollection>);
    expect(line("GPT-5")).toBe(line("Publicerad")?.parentElement);
    cleanup();

    // A description left empty has no place to take: the tokens keep theirs.
    renderInApp(<ResourceCollection>{row("")}</ResourceCollection>);
    expect(line("GPT-5")).toBe(line("Publicerad")?.parentElement);
    cleanup();

    renderInApp(<ResourceCollection>{row("Svarar på frågor.")}</ResourceCollection>);
    expect(line("Svarar på frågor.")).toBe(line("Publicerad")?.parentElement);
    expect(line("GPT-5")).not.toBe(line("Publicerad")?.parentElement);
  });

  it("keeps the rows on a phone turned sideways, without a grid of cards", () => {
    setViewport("phone-landscape");
    renderInApp(<Collection />);
    const rows = screen.getAllByRole("list")[0]!;
    expect(rows.className).not.toContain("auto-fill");
    expect(within(rows).getAllByRole("listitem")[0]!.className).toContain("astryx-item");
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

it("keeps focus on the same resource when a chosen desktop table replaces its card", () => {
  const view = renderInApp(<Collection />);
  act(() => screen.getByRole("button", { name: /^Fler åtgärder/ }).focus());
  view.rerender(
    <Collection
      desktopList={
        <table aria-label="Result">
          <tbody>
            <tr>
              <td>
                <a href="/spaces/s1/apps/a1">Protokollsammanfattning</a>
              </td>
            </tr>
          </tbody>
        </table>
      }
    />
  );
  expect(document.activeElement).toBe(within(screen.getByRole("table")).getByRole("link"));
  expect(document.activeElement?.getAttribute("href")).toBe("/spaces/s1/apps/a1");
});
