// @vitest-environment jsdom
import { fireEvent } from "@testing-library/react";
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

  it("is the pressed button when the browser never focused it (Safari, iOS)", () => {
    html(`<button id="edit">Redigera</button>`);
    // Safari fires the pointer events and the click but leaves focus on <body>.
    fireEvent.pointerDown(byId("edit"));
    fireEvent.click(byId("edit"));
    expect(document.activeElement).toBe(document.body);
    expect(returnTarget()).toBe(byId("edit"));
  });

  it("is the pressable control around what was pressed (an icon in a link)", () => {
    html(`<a id="link" href="/x"><svg id="icon"></svg></a>`);
    fireEvent.pointerDown(byId("icon"));
    expect(returnTarget()).toBe(byId("link"));
  });

  it("forgets a press once focus moves or a key is pressed", () => {
    html(`<button id="edit">Redigera</button><input id="field" />`);
    fireEvent.pointerDown(byId("edit"));
    byId("field").focus();
    byId("field").blur();
    expect(returnTarget()).toBeNull();

    fireEvent.pointerDown(byId("edit"));
    fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    expect(returnTarget()).toBeNull();
  });

  it("is nothing when focus is on the page and nothing focused has left it", () => {
    html(`<button id="edit">Redigera</button>`);
    byId("edit").focus();
    byId("edit").blur();
    expect(returnTarget()).toBeNull();
  });
});
