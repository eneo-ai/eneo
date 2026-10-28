// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useState, useSyncExternalStore } from "react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { SidePanel } from "./side-panel";
import { SidePanelStore } from "./side-panel-store";

// The file panel's code arrives on demand. A test decides when it arrives
// (`gate`) and whether it can be fetched (`fail`: its chunk is gone after a
// deploy). A failed import is tried again on the next load; a loaded one stays.
const state = vi.hoisted(() => ({
  loads: 0,
  fail: true,
  gate: Promise.resolve() as Promise<void>
}));
vi.mock("./file-panel", async (importOriginal) => {
  state.loads += 1;
  await state.gate;
  if (state.fail) throw new Error("Failed to fetch dynamically imported module");
  return importOriginal();
});
vi.mock("@/features/workspace/preview/load-preview", () => ({
  loadPreview: vi.fn(async () => ({ kind: "text", text: "Text", truncated: false })),
  PreviewTooLargeError: class extends Error {}
}));

// Transforming the real panel (the editor stack) can take over a second on a
// cold cache; do it once up front so the tests time the panel, not the build.
beforeAll(async () => {
  await vi.importActual("./file-panel");
});

afterEach(cleanup);

const file = {
  id: "file-1",
  name: "Policy.txt",
  mimetype: "text/plain",
  size: 5
};

function Harness({ onPanel }: { onPanel: (panel: SidePanelStore) => void }) {
  setViewport("desktop");
  const [panel] = useState(() => {
    const store = new SidePanelStore(() => Promise.reject(new Error("unused")));
    onPanel(store);
    return store;
  });
  // The chat view re-renders the panel on every change of the store.
  useSyncExternalStore(panel.subscribe, panel.getVersion);
  return (
    <SidePanel
      panel={panel}
      messages={[]}
      contents={{ views: [], documents: [], uploads: [file] }}
      versionsOf={() => []}
      exportOf={() => null}
      saverOf={() => null}
      activity={null}
      latestActivity={null}
    >
      <p>The conversation</p>
    </SidePanel>
  );
}

async function openFile(): Promise<SidePanelStore> {
  let panel: SidePanelStore | null = null;
  renderInApp(<Harness onPanel={(store) => (panel = store)} />);
  await act(async () => panel!.open(file, null));
  return panel!;
}

it("keeps a panel whose code failed to load inside the panel, with a retry", async () => {
  const panel = await openFile();

  // The failure stays in the file's frame; the conversation is still there.
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("Innehållet kunde inte hämtas");
  expect(screen.getByText("The conversation")).toBeTruthy();
  expect(screen.getByText("Policy.txt")).toBeTruthy();

  // A retry is a new load, not the failed one again.
  const attempts = state.loads;
  fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(state.loads).toBeGreaterThan(attempts);

  // The frame still closes the panel.
  fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
  expect(panel.occupant).toEqual({ kind: "closed" });
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps the focus in the panel when a retry replaces the failed frame", async () => {
  await openFile();
  const retry = await screen.findByRole("button", { name: "Försök igen" });
  retry.focus();

  // A keyboard user presses Enter on it.
  fireEvent.keyDown(retry, { key: "Enter" });
  fireEvent.click(retry);
  await screen.findByRole("alert");

  expect(document.activeElement).not.toBe(document.body);
  expect(document.activeElement?.closest("aside")).not.toBeNull();
});

it("loads the panel on a retry after a failure, keeping the focus in the panel", async () => {
  await openFile();
  const retry = await screen.findByRole("button", { name: "Försök igen" });
  retry.focus();

  // The code can be fetched again, and arrives a moment after the retry.
  state.fail = false;
  let arrive = () => {};
  state.gate = new Promise((resolve) => (arrive = resolve));
  fireEvent.keyDown(retry, { key: "Enter" });
  fireEvent.click(retry);
  expect(await screen.findByText("Läser in förhandsgranskningen...")).toBeTruthy();
  expect(document.activeElement?.closest("aside")).not.toBeNull();

  // The loading frame's close button has the focus when the panel arrives.
  screen.getByRole("button", { name: "Stäng" }).focus();
  await act(async () => arrive());
  // Only the loaded panel's header gives the file's kind and size.
  expect(await screen.findByText("TXT · 5 B")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(document.activeElement).not.toBe(document.body);
  expect(document.activeElement?.closest("aside")).not.toBeNull();
});
