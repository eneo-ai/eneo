// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { App } from "../apps";
import { InstructionsSection } from "./instructions-section";
const api = vi.hoisted(() => ({ GET: vi.fn() }));
const update = vi.hoisted(() => vi.fn<(body: unknown) => Promise<unknown>>().mockResolvedValue({}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("./use-app", () => ({
  useUpdateApp: () => useMutation({ mutationFn: (body: unknown) => update(body) })
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("restores the shared typed prompt with provenance through app autosave", async () => {
  const old = {
    id: "old",
    text: "App restored body",
    description: "Historical app marker",
    created_at: "2026-10-01T12:00:00Z",
    is_selected: false,
    user: { id: "user-1", email: "owner@example.se" }
  };
  api.GET.mockImplementation(async (path) => ({
    data: path.includes("/prompts/{id}") ? old : { items: [old] },
    response: new Response("{}")
  }));
  renderInApp(
    <InstructionsSection
      app={{ id: "app", prompt: { text: "Current app body" } } as unknown as App}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Visa prompthistorik" }));
  fireEvent.click(await screen.findByRole("button", { name: /Historical app marker/ }));
  await screen.findByText("App restored body");
  fireEvent.click(
    screen.getByRole("button", { name: /Återställ denna version|Använd denna version/ })
  );
  await waitFor(() =>
    expect(update).toHaveBeenCalledWith({
      prompt: {
        text: "App restored body",
        description: expect.stringMatching(/^Återställd prompt från /)
      }
    })
  );
});
