// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { DRAWER_MARKER, isOtherDialogOpen } from "./shell-context";

afterEach(() => {
  document.body.innerHTML = "";
});

function add(tag: string, attributes: Record<string, string>) {
  const element = document.body.appendChild(document.createElement(tag));
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

it("sees open modal dialogs, but not the nav drawer", () => {
  expect(isOtherDialogOpen()).toBe(false);

  add("dialog", { [DRAWER_MARKER]: "", open: "" });
  expect(isOtherDialogOpen()).toBe(false);

  // A Radix popover is not a dialog the palette would fight with.
  add("div", { role: "dialog", "data-state": "open" });
  expect(isOtherDialogOpen()).toBe(false);

  add("dialog", {});
  expect(isOtherDialogOpen()).toBe(false);

  add("dialog", { open: "" });
  expect(isOtherDialogOpen()).toBe(true);
});
