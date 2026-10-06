// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isFocusLost, rescueFocus } from "./focus-rescue";

let panel: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  panel = document.createElement("div");
  panel.tabIndex = -1;
  document.body.append(panel);
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

it("moves focus to the target when the focused row was removed", () => {
  const row = document.createElement("button");
  document.body.append(row);
  row.focus();
  row.remove();
  expect(document.activeElement).toBe(document.body);

  rescueFocus(panel);
  vi.advanceTimersByTime(500);

  expect(document.activeElement).toBe(panel);
});

it("leaves focus alone when it is still on something", () => {
  const other = document.createElement("button");
  document.body.append(other);
  other.focus();

  rescueFocus(panel);
  vi.advanceTimersByTime(500);

  expect(document.activeElement).toBe(other);
});

it("leaves focus in a menu the user opened in the meantime", () => {
  const row = document.createElement("button");
  document.body.append(row);
  row.focus();
  row.remove();

  rescueFocus(panel);
  // Before the second check the user opens a row's menu.
  document.body.insertAdjacentHTML(
    "beforeend",
    '<div role="menu" data-state="open"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>'
  );
  document.getElementById("item")!.focus();
  vi.advanceTimersByTime(500);

  expect(document.activeElement?.id).toBe("item");
});

describe("isFocusLost", () => {
  it("is lost on the body and in a closed dialog, not on a button or an open menu", () => {
    document.body.innerHTML = `
      <button id="page">Sida</button>
      <dialog id="dialog"><button id="inside">Stäng</button></dialog>
      <div role="menu"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>
    `;
    expect(isFocusLost()).toBe(true);
    document.getElementById("inside")!.focus();
    expect(isFocusLost()).toBe(true);
    document.getElementById("item")!.focus();
    expect(isFocusLost()).toBe(false);
    document.getElementById("page")!.focus();
    expect(isFocusLost()).toBe(false);
  });

  it("is lost on an item of a menu that is closing or hidden", () => {
    document.body.innerHTML = `
      <div role="menu" data-state="closed"><div id="radix" role="menuitem" tabindex="-1">A</div></div>
      <div hidden><div role="menu"><div id="hidden" role="menuitem" tabindex="-1">B</div></div></div>
    `;
    for (const id of ["radix", "hidden"]) {
      document.getElementById(id)!.focus();
      expect(isFocusLost()).toBe(true);
    }
  });

  it("reads an Astryx menu's popover state where the Popover API exists", () => {
    // jsdom has no Popover API: pretend it has, with an open or a hidden popover.
    Object.defineProperty(HTMLElement.prototype, "showPopover", {
      configurable: true,
      value: () => {}
    });
    const matches = Element.prototype.matches;
    let popoverOpen = false;
    const spy = vi.spyOn(Element.prototype, "matches").mockImplementation(function (
      this: Element,
      selector: string
    ) {
      return selector === ":popover-open" ? popoverOpen : matches.call(this, selector);
    });
    try {
      document.body.innerHTML = `
        <div popover="auto"><div role="menu"><div id="item" role="menuitem" tabindex="-1">A</div></div></div>
      `;
      document.getElementById("item")!.focus();
      expect(isFocusLost()).toBe(true);
      popoverOpen = true;
      expect(isFocusLost()).toBe(false);
    } finally {
      spy.mockRestore();
      delete (HTMLElement.prototype as Partial<HTMLElement>).showPopover;
    }
  });
});
