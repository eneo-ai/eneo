// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useState, useSyncExternalStore } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import type { SidePanelStore as Store } from "./side-panel-store";

// The file panel's code arrives when a test opens its gate. Each test starts
// from fresh modules and a fresh mock (resetModules keeps mocked modules), so
// its panel loads the code anew.
let arrive = () => {};
beforeEach(() => {
  vi.resetModules();
  const gate = new Promise<void>((resolve) => (arrive = resolve));
  vi.doMock("./file-panel", async () => {
    await gate;
    return { FilePanel: () => <button type="button">Inside the loaded panel</button> };
  });
});
afterEach(cleanup);

const file = { id: "file-1", name: "Policy.txt", mimetype: "text/plain", size: 5 };

async function renderPanel(): Promise<Store> {
  const { SidePanel } = await import("./side-panel");
  const { SidePanelStore } = await import("./side-panel-store");
  let panel: Store | null = null;
  function Harness() {
    setViewport("desktop");
    const [store] = useState(() => {
      const created = new SidePanelStore(() => Promise.reject(new Error("unused")));
      panel = created;
      return created;
    });
    // The chat view re-renders the panel on every change of the store.
    useSyncExternalStore(store.subscribe, store.getVersion);
    return (
      <SidePanel
        panel={store}
        messages={[]}
        contents={{ views: [], documents: [], uploads: [file] }}
        versionsOf={() => []}
        exportOf={() => null}
        saverOf={() => null}
        activity={null}
        latestActivity={null}
      >
        <button type="button">In the conversation</button>
      </SidePanel>
    );
  }
  renderInApp(<Harness />);
  return panel!;
}

async function openedByItself(): Promise<Store> {
  const panel = await renderPanel();
  (document.activeElement as HTMLElement | null)?.blur();
  await act(async () => {
    panel.beginAnswer();
    panel.arrive(file);
  });
  expect(panel.openedByItself).toBe(true);
  return panel;
}

async function codeArrives() {
  await act(async () => arrive());
  expect(await screen.findByRole("button", { name: "Inside the loaded panel" })).toBeTruthy();
}

it("leaves the focus where it is when the reader never entered the loading panel", async () => {
  await openedByItself();
  await codeArrives();
  expect(document.activeElement).toBe(document.body);
});

it("keeps the focus in a panel that opened by itself when the reader focused its loading frame", async () => {
  await openedByItself();
  screen.getByRole("button", { name: "Stäng" }).focus();
  await codeArrives();
  expect(document.activeElement?.closest("aside")).not.toBeNull();
});

it("keeps the focus in the panel when the reader used a control of the loading frame by keyboard", async () => {
  await openedByItself();
  const maximise = screen.getByRole("button", { name: "Maximera" });
  maximise.focus();
  fireEvent.keyDown(maximise, { key: "Enter" });
  fireEvent.click(maximise);
  // The control stays focused, now offering to restore the size.
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Återställ storlek" }));

  await codeArrives();
  expect(document.activeElement).not.toBe(document.body);
  expect(document.activeElement?.closest("aside")).not.toBeNull();
});

it("leaves the focus where it is when the reader left the loading panel before the code arrived", async () => {
  const panel = await renderPanel();
  await act(async () => panel.open(file, null));
  screen.getByRole("button", { name: "Stäng" }).focus();
  // The reader clicks into the conversation, then on its text.
  const outside = screen.getByRole("button", { name: "In the conversation" });
  fireEvent.pointerDown(outside);
  outside.focus();
  fireEvent.pointerDown(document.body);
  outside.blur();
  await codeArrives();
  expect(document.activeElement).toBe(document.body);
});

it("shows a panel whose code is already here without a loading frame", async () => {
  const first = await renderPanel();
  await act(async () => first.open(file, null));
  await codeArrives();
  cleanup();

  // The same page opens a file again in another conversation: the code is here.
  const panel = await renderPanel();
  const shown: string[] = [];
  const watcher = new MutationObserver(() => {
    if (document.body.textContent?.includes("Läser in förhandsgranskningen")) shown.push("loading");
  });
  watcher.observe(document.body, { subtree: true, childList: true, characterData: true });
  await act(async () => panel.open(file, null));
  expect(await screen.findByRole("button", { name: "Inside the loaded panel" })).toBeTruthy();
  watcher.disconnect();
  expect(shown).toEqual([]);
});
