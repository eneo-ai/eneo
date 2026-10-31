// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { PromptVersionDialog } from "./prompt-version-dialog";
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const own = { id: "user-1", email: "owner@example.se" };
const current = {
  id: "current",
  is_selected: true,
  user: own,
  description: "Current note",
  text: "Current text",
  created_at: "2026-10-30T12:00:00Z"
};
const old = {
  ...current,
  id: "old",
  is_selected: false,
  description: "Old note",
  text: "Old text"
};
const other = {
  ...old,
  id: "other",
  user: { id: "someone", email: "other@example.se" },
  description: "Other note"
};
let versions = [current, old, other];
beforeEach(() => {
  versions = [current, old, other];
  api.GET.mockImplementation(async (path, init) => ({
    data: path.includes("/prompts/{id}")
      ? versions.find((v) => v.id === init.params.path.id)
      : { items: versions },
    response: new Response("{}")
  }));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function show() {
  const restore = vi.fn();
  renderInApp(
    <PromptVersionDialog
      resource={{ type: "assistant", id: "assistant" }}
      open
      onOpenChange={vi.fn()}
      onUseVersion={restore}
    />
  );
  return restore;
}
it("previews the current version and author, blocks current restore and non-author mutations", async () => {
  show();
  await screen.findByText("Current text");
  expect(
    (screen.getByRole("button", { name: "Återställ denna version" }) as HTMLButtonElement).disabled
  ).toBe(true);
  expect(
    (screen.getByRole("button", { name: "Radera prompt" }) as HTMLButtonElement).disabled
  ).toBe(true);
  expect(screen.getAllByText(/owner@example.se/).length).toBeGreaterThan(0);
  await expectNoAxeViolations(document.body);
  fireEvent.click(screen.getByRole("button", { name: /Other note/ }));
  await screen.findByText("Old text");
  expect(
    (screen.getByRole("button", { name: "Redigera beskrivning" }) as HTMLButtonElement).disabled
  ).toBe(true);
  expect(
    (screen.getByRole("button", { name: "Radera prompt" }) as HTMLButtonElement).disabled
  ).toBe(true);
});
it("keeps a failed description draft for retry, updates preview and confirms historical deletion", async () => {
  api.PATCH.mockRejectedValueOnce(new Error("failed")).mockImplementation(async (_path, init) => {
    versions = versions.map((v) =>
      v.id === "old" ? { ...v, description: init.body.description } : v
    );
    return { data: versions[1], response: new Response("{}") };
  });
  api.DELETE.mockImplementation(async () => {
    versions = versions.filter((v) => v.id !== "old");
    return { data: undefined, response: new Response(null, { status: 204 }) };
  });
  show();
  fireEvent.click(await screen.findByRole("button", { name: /Old note/ }));
  await screen.findByText("Old text");
  fireEvent.click(screen.getByRole("button", { name: "Redigera beskrivning" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
    target: { value: "Revised note" }
  });
  fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  expect((screen.getByRole("textbox", { name: "Beskrivning" }) as HTMLTextAreaElement).value).toBe(
    "Revised note"
  );
  fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  await screen.findAllByText("Revised note");
  fireEvent.click(screen.getByRole("button", { name: "Radera prompt" }));
  expect(api.DELETE).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Ta bort" }));
  await waitFor(() =>
    expect(api.DELETE).toHaveBeenCalledWith(
      "/api/v1/prompts/{id}/",
      expect.objectContaining({ params: { path: { id: "old" } } })
    )
  );
});
it("restores typed version metadata through the parent owner", async () => {
  const restore = show();
  fireEvent.click(await screen.findByRole("button", { name: /Old note/ }));
  await screen.findByText("Old text");
  fireEvent.click(screen.getByRole("button", { name: "Återställ denna version" }));
  expect(restore).toHaveBeenCalledWith(
    expect.objectContaining({ id: "old", text: "Old text", created_at: old.created_at })
  );
});

it("clears a historical selection when the parent resource changes", async () => {
  const second = {
    ...current,
    id: "second",
    text: "Second resource prompt",
    description: "Second current marker"
  };
  api.GET.mockImplementation(async (path, init) => ({
    data: path.includes("/prompts/{id}")
      ? init.params.path.id === "second"
        ? second
        : versions.find((v) => v.id === init.params.path.id)
      : { items: init.params.path.id === "second-resource" ? [second] : versions },
    response: new Response("{}")
  }));
  const props = { open: true, onOpenChange: vi.fn(), onUseVersion: vi.fn() };
  const view = renderInApp(
    <PromptVersionDialog {...props} resource={{ type: "assistant", id: "first-resource" }} />
  );
  fireEvent.click(await screen.findByRole("button", { name: /Old note/ }));
  await screen.findByText("Old text");
  view.rerender(
    <PromptVersionDialog {...props} resource={{ type: "assistant", id: "second-resource" }} />
  );
  expect(await screen.findByText("Second resource prompt")).toBeTruthy();
  expect(screen.queryByText("Old text")).toBeNull();
  expect(
    (screen.getByRole("button", { name: "Återställ denna version" }) as HTMLButtonElement).disabled
  ).toBe(true);
});

it("names the dialog when opened after its parent was mounted closed", async () => {
  const props = {
    resource: { type: "assistant" as const, id: "assistant" },
    onOpenChange: vi.fn(),
    onUseVersion: vi.fn()
  };
  const view = renderInApp(<PromptVersionDialog {...props} open={false} />);
  view.rerender(<PromptVersionDialog {...props} open />);
  await screen.findByText("Current text");
  expect(screen.getByRole("dialog", { name: "Prompthistorik" })).toBeTruthy();
});
