// @vitest-environment jsdom
import { fireEvent, renderHook } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { returnTarget, trackFocus, useReturnFocus } from "./dialog-focus";

const notifyFocusLost = vi.hoisted(() => vi.fn());
vi.mock("@/lib/focus-rescue", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/focus-rescue")>()),
  notifyFocusLost
}));

beforeAll(trackFocus);
afterEach(() => {
  document.body.innerHTML = "";
  notifyFocusLost.mockClear();
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

describe("useReturnFocus", () => {
  const noTrigger = { current: null };

  /** A dialog opened from the Edit button, as Astryx opens it: focus moves inside. */
  function openFromEdit() {
    html(
      `<button id="edit">Redigera</button><dialog id="dialog"><button id="inside">Stäng</button></dialog>`
    );
    byId("edit").focus();
    const hook = renderHook(({ open }) => useReturnFocus(open, noTrigger), {
      initialProps: { open: true }
    });
    const dialog = byId("dialog") as HTMLDialogElement;
    dialog.showModal();
    expect(document.activeElement).toBe(byId("inside"));
    return { hook, dialog };
  }

  it("does not report when the dialog returned focus itself", () => {
    const { hook, dialog } = openFromEdit();
    dialog.close();
    byId("edit").focus();

    hook.rerender({ open: false });

    expect(document.activeElement).toBe(byId("edit"));
    expect(notifyFocusLost).not.toHaveBeenCalled();
  });

  it("returns focus to the opener and does not report when that worked", () => {
    const { hook, dialog } = openFromEdit();
    dialog.close();

    hook.rerender({ open: false });

    expect(document.activeElement).toBe(byId("edit"));
    expect(notifyFocusLost).not.toHaveBeenCalled();
  });

  it("reports once when the opener is gone and focus stays lost", () => {
    const { hook, dialog } = openFromEdit();
    byId("edit").remove();
    dialog.close();

    hook.rerender({ open: false });

    expect(notifyFocusLost).toHaveBeenCalledTimes(1);
    hook.unmount();
    expect(notifyFocusLost).toHaveBeenCalledTimes(1);
  });

  it("reports once when the dialog unmounts while open and the opener is gone", () => {
    const { hook, dialog } = openFromEdit();
    byId("edit").remove();
    dialog.remove();
    expect(document.activeElement).toBe(document.body);

    hook.unmount();

    expect(notifyFocusLost).toHaveBeenCalledTimes(1);
  });

  it("returns focus to the opener when the dialog unmounts while open", () => {
    const { hook, dialog } = openFromEdit();
    dialog.remove();

    hook.unmount();

    expect(document.activeElement).toBe(byId("edit"));
    expect(notifyFocusLost).not.toHaveBeenCalled();
  });
});
