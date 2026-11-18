// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { AppEditor } from "./app-editor";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
vi.mock("@/features/skills/use-can-attach-skills", () => ({ useCanAttachSkills: () => false }));
vi.mock("./general-section", () => ({ GeneralSection: () => null }));
vi.mock("./input-section", () => ({ InputSection: () => null }));
vi.mock("./instructions-section", () => ({ InstructionsSection: () => null }));
vi.mock("./attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("./ai-section", () => ({ AiSection: () => null }));
vi.mock("./security-section", () => ({ SecuritySection: () => null }));
vi.mock("./publishing-section", () => ({ PublishingSection: () => null }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(permissions: string[]) {
  state.space = makeSpace();
  api.GET.mockResolvedValue({ data: { items: [], count: 0 }, response: new Response("{}") });
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], {
    id: "app-1",
    name: "Protokoll",
    permissions,
    attachments: [],
    prompt: null,
    completion_model: null
  });
  return renderInApp(<AppEditor appId="app-1" />, {
    queryClient,
    route: "/spaces/space-1/apps/app-1/edit"
  });
}

it("omits the entire API keys section and its queries without app-edit permission", async () => {
  show(["read"]);
  expect(screen.queryByRole("heading", { name: "API-nycklar" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "API-nycklar" })).toBeNull();
  await waitFor(() => expect(api.GET).not.toHaveBeenCalled());
});

it("mounts the existing API keys section and queries for an app editor", async () => {
  show(["read", "edit"]);
  expect(screen.getByRole("heading", { name: "API-nycklar" })).toBeTruthy();
  await waitFor(() =>
    expect(
      api.GET.mock.calls.some(([path]) => path === "/api/v1/api-keys/notification-subscriptions")
    ).toBe(true)
  );
});

it("lists its sections on a phone's index under the same groups as the assistant editor", () => {
  show(["read", "edit", "publish"]);
  const groups = [...document.querySelectorAll("[data-editor-index] > div")].map((group) => [
    group.querySelector("h2")?.textContent,
    [...group.querySelectorAll("[data-editor-row]")].map((row) =>
      row.getAttribute("data-editor-row")
    )
  ]);
  expect(groups).toEqual([
    ["Innehåll", ["general", "input", "instructions", "attachments"]],
    ["Modell och funktioner", ["ai"]],
    ["Åtkomst", ["security", "api-keys", "publishing"]]
  ]);
});
