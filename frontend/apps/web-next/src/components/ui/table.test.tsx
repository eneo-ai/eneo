// @vitest-environment jsdom
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { Table, TableBody, TableCell, TableRow } from "./table";

// jsdom has no layout: give the scroll container a width and content wider
// than it, the way Astryx tests its scrollable-area hook.
function overflow(element: HTMLElement, contentWidth: number) {
  for (const [key, value] of Object.entries({
    clientWidth: 300,
    clientHeight: 100,
    scrollWidth: contentWidth,
    scrollHeight: 100,
    scrollLeft: 0,
    scrollTop: 0
  })) {
    Object.defineProperty(element, key, { configurable: true, value, writable: true });
  }
}

function UsageTable({ name }: { name?: string }) {
  return (
    <Table aria-label={name} aria-labelledby={name ? undefined : "usage-heading"}>
      <TableBody>
        <TableRow>
          <TableCell>claude-haiku-4-5</TableCell>
          <TableCell>12 345</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

it("activates actionable rows with pointer and keyboard", () => {
  const onRowAction = vi.fn();

  renderInApp(
    <Table>
      <TableBody>
        <TableRow aria-label="Open details" onRowAction={onRowAction}>
          <TableCell>Details</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );

  const row = screen.getByRole("row", { name: "Open details" });
  fireEvent.click(row);
  fireEvent.keyDown(row, { key: "Enter" });
  fireEvent.keyDown(row, { key: " " });
  fireEvent.keyDown(row, { key: "Escape" });

  expect(row.getAttribute("tabindex")).toBe("0");
  expect(onRowAction).toHaveBeenCalledTimes(3);
});

describe("Table", () => {
  let frames: FrameRequestCallback[];

  beforeEach(() => {
    frames = [];
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => frames.push(callback))
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const native = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      (element) =>
        new Proxy(native(element), {
          get: (target, property) =>
            property === "overflowX" ? "auto" : Reflect.get(target, property, target)
        })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function measure(container: HTMLElement, contentWidth: number) {
    overflow(container, contentWidth);
    act(() => {
      container.dispatchEvent(new Event("scroll"));
      frames.splice(0).forEach((frame) => frame(performance.now()));
    });
  }

  it("makes a table that doesn't fit a named keyboard stop (2.1.1)", () => {
    renderInApp(<UsageTable name="Tokenanvändning" />);
    const container = screen.getByRole("group", { name: "Tokenanvändning" });
    expect(container.hasAttribute("tabindex")).toBe(false);

    measure(container, 900);
    expect(container.getAttribute("tabindex")).toBe("0");

    measure(container, 300);
    expect(container.hasAttribute("tabindex")).toBe(false);
  });

  it("names the scroll container after the heading that names the table", () => {
    renderInApp(
      <>
        <h2 id="usage-heading">Lagring per yta</h2>
        <UsageTable />
      </>
    );
    expect(screen.getByRole("group", { name: "Lagring per yta" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Lagring per yta" })).toBeTruthy();
  });
});
