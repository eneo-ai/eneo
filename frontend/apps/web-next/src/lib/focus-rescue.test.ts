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

describe("isFocusLost", () => {
  it("is lost on the body, in a closed dialog or on a menu item, not on a button", () => {
    document.body.innerHTML = `
      <button id="page">Sida</button>
      <dialog id="dialog"><button id="inside">Stäng</button></dialog>
      <div role="menu"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>
    `;
    expect(isFocusLost()).toBe(true);
    document.getElementById("inside")!.focus();
    expect(isFocusLost()).toBe(true);
    document.getElementById("item")!.focus();
    expect(isFocusLost()).toBe(true);
    document.getElementById("page")!.focus();
    expect(isFocusLost()).toBe(false);
  });
});
