// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { rescueFocus } from "./focus-rescue";

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
