// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { returnTarget, trackFocus } from "./dialog-focus";

beforeAll(trackFocus);
afterEach(() => {
  document.body.innerHTML = "";
});

function html(markup: string) {
  document.body.innerHTML = markup;
}

function byId(id: string) {
  return document.getElementById(id)!;
}

describe("returnTarget", () => {
  it("is the element that has focus when the dialog opens", () => {
    html(`<button id="edit">Redigera</button>`);
    byId("edit").focus();
    expect(returnTarget()).toBe(byId("edit"));
  });

  it("is the menu button when an Astryx menu item has focus (aria-controls)", () => {
    html(`
      <button id="more" aria-haspopup="menu" aria-controls="menu-1">Fler åtgärder</button>
      <div id="menu-1" role="menu"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>
    `);
    byId("item").focus();
    expect(returnTarget()).toBe(byId("more"));
  });

  it("is the menu button when the focused Radix menu item is already gone (aria-labelledby)", () => {
    html(`
      <button id="actions" aria-haspopup="menu">Åtgärder</button>
      <div role="menu" aria-labelledby="actions"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>
    `);
    byId("item").focus();
    byId("item").closest('[role="menu"]')!.remove();
    expect(document.activeElement).toBe(document.body);
    expect(returnTarget()).toBe(byId("actions"));
  });

  it("is nothing when focus is on the page and nothing focused has left it", () => {
    html(`<button id="edit">Redigera</button>`);
    byId("edit").focus();
    byId("edit").blur();
    expect(returnTarget()).toBeNull();
  });
});
