// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { SessionSnapshot } from "@/lib/api/refusal";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { BrowserSessionBoundary } from "./browser-session";

const session = vi.hoisted(() => ({
  snapshot: { status: "bound", generation: "a" } as SessionSnapshot,
  listeners: new Set<() => void>(),
  check: vi.fn(async () => {}),
  reload: vi.fn(),
  cleanup: vi.fn()
}));
vi.mock("@/lib/api/refusal", () => ({
  getSessionSnapshot: () => session.snapshot,
  subscribeSession: (listener: () => void) => {
    session.listeners.add(listener);
    return () => session.listeners.delete(listener);
  },
  listenForSessionResume: () => session.cleanup,
  checkBrowserSession: session.check,
  reloadSession: session.reload
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/runtime-config", () => ({
  runtimeConfig: () => ({ accessibility_statement_url: null })
}));

beforeEach(() => {
  vi.clearAllMocks();
  session.snapshot = { status: "bound", generation: "a" };
});
afterEach(cleanup);

function update(snapshot: SessionSnapshot) {
  act(() => {
    session.snapshot = snapshot;
    session.listeners.forEach((listener) => listener());
  });
}

it("replaces authenticated controls with a focused accessible explanation and explicit reload", async () => {
  const { container, unmount } = renderInApp(
    <BrowserSessionBoundary>
      <main>
        <button>Save draft</button>
      </main>
    </BrowserSessionBoundary>
  );
  screen.getByRole("button", { name: "Save draft" }).focus();
  update({ status: "stale", destination: "/login" });
  expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
  expect(document.activeElement).toBe(
    screen.getByRole("heading", { name: "Sessionen har ändrats" })
  );
  fireEvent.click(screen.getByRole("button", { name: "Ladda om sidan" }));
  expect(session.reload).toHaveBeenCalledTimes(1);
  await expectNoAxeViolations(container);
  unmount();
  expect(session.cleanup).toHaveBeenCalledTimes(1);
  expect(session.listeners.size).toBe(0);
});

it("keeps the editor mounted on a failed check and offers retry", async () => {
  const { container } = renderInApp(
    <BrowserSessionBoundary>
      <main>
        <label>
          Draft
          <input defaultValue="unsaved draft" />
        </label>
      </main>
    </BrowserSessionBoundary>
  );
  const input = screen.getByRole("textbox", { name: "Draft" });
  update({ status: "bound", generation: "a", checkError: new TypeError("Offline") });
  expect(screen.getByRole("textbox", { name: "Draft" })).toBe(input);
  expect((input as HTMLInputElement).value).toBe("unsaved draft");
  expect(screen.getByRole("alert")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
  expect(session.check).toHaveBeenCalledTimes(1);
  await expectNoAxeViolations(container);
  update({ status: "bound", generation: "a" });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("textbox", { name: "Draft" })).toBe(input);
});

it("never exposes logout children from a previously bound suspended document", async () => {
  window.history.replaceState({}, "", "/logout");
  renderInApp(
    <BrowserSessionBoundary>
      <main>
        <button>Private action</button>
      </main>
    </BrowserSessionBoundary>
  );
  update({ status: "stale", destination: "/deactivated" });
  expect(screen.queryByRole("button", { name: "Private action" })).toBeNull();
  expect(screen.getByRole("heading", { name: messages.organisation_deactivated })).toBeTruthy();
  expect(document.activeElement).toBe(
    screen.getByRole("heading", { name: messages.organisation_deactivated })
  );
  expect(screen.getByRole("link", { name: "Logga ut" }).getAttribute("href")).toBe("/logout");
  await expectNoAxeViolations();
});
