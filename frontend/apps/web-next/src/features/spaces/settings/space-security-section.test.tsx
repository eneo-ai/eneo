// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import type { Schema } from "@/lib/api/models";
import type { Space } from "../space";
import { makeSpace } from "../testing/space-fixture";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
import { SpaceSettings } from "./space-settings";

const classifications: Schema<"SecurityClassificationPublic">[] = [
  { id: "internal", name: "Intern", description: null, security_level: 2 },
  { id: "secret", name: "Hemlig", description: null, security_level: 3 }
];
const emptyImpact = (): Schema<"UpdateSpaceDryRunResponse"> => ({
  assistants: [],
  group_chats: [],
  apps: [],
  services: [],
  completion_models: [],
  embedding_models: [],
  transcription_models: [],
  mcp_servers: [],
  capabilities: []
});
let impact = emptyImpact();
let modelChanged = false;
const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
beforeEach(() => {
  state.space = makeSpace({
    overrides: { security_classification: classifications[0], completion_models: [] }
  });
  impact = emptyImpact();
  modelChanged = false;
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/security-classifications/")
      return ok({ security_enabled: true, security_classifications: classifications });
    if (path.endsWith("/impact-analysis/")) return ok(impact);
    if (path === "/api/v1/ai-models/")
      return ok({
        completion_models: [
          {
            id: modelChanged ? "new" : "old",
            name: modelChanged ? "Efter klassning" : "Före klassning",
            is_org_enabled: true,
            is_deprecated: false
          }
        ],
        embedding_models: [],
        transcription_models: []
      });
    return ok({ items: [] });
  });
  api.PATCH.mockImplementation(
    (_path: string, { body }: { body: Schema<"PartialUpdateSpaceRequest"> }) => {
      modelChanged = true;
      state.space = {
        ...state.space,
        security_classification:
          classifications.find((item) => item.id === body.security_classification?.id) ?? null
      };
      return ok(state.space);
    }
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
async function choose(name: string) {
  const section = document.getElementById("security")!;
  fireEvent.click(await within(section).findByRole("combobox"));
  fireEvent.click(await screen.findByRole("option", { name }));
  return screen.findByRole("alertdialog");
}

it("requires confirmation for capability-only impact and names the affected capability", async () => {
  impact = { ...emptyImpact(), capabilities: ["web_search"] };
  renderInApp(<SpaceSettings />);
  const dialog = await choose("Hemlig");
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(within(dialog).getByText("Webbsökning", { exact: true })).toBeTruthy();
  expect(within(dialog).getByText("Hemlig", { exact: true })).toBeTruthy();
  await expectNoAxeViolations(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { security_classification: { id: "secret" } }
    })
  );
});

it.each(["—", "Hemlig"])(
  "confirms zero impact for %s, can cancel and then saves its reviewed target",
  async (target) => {
    renderInApp(<SpaceSettings />);
    let dialog = await choose(target);
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(within(dialog).getByText("0 resurser kommer att påverkas")).toBeTruthy();
    if (target === "—")
      expect(
        api.GET.mock.calls.filter(([path]) => path.endsWith("/impact-analysis/"))
      ).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(api.PATCH).not.toHaveBeenCalled();
    dialog = await choose(target);
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
        params: { path: { id: "space-1" } },
        body: { security_classification: target === "—" ? null : { id: "secret" } }
      })
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  }
);

it("keeps named impact after a failed save and refreshes visible models on successful retry", async () => {
  impact.assistants = [
    { id: "assistant", name: "Berörd assistent", user_id: "user", type: "assistant" }
  ];
  renderInApp(<SpaceSettings />);
  fireEvent.click(await screen.findByRole("button", { name: "Välj modeller, Chattmodeller" }));
  await screen.findByRole("switch", { name: "Före klassning" });
  api.PATCH.mockResolvedValueOnce({
    error: { message: "Fixture save refused" },
    response: new Response("{}", { status: 400 })
  });
  const dialog = await choose("Hemlig");
  expect(within(dialog).getByText("Berörd assistent")).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  const retry = await within(dialog).findByRole("button", { name: "Bekräfta" });
  await waitFor(() => expect(retry.getAttribute("aria-busy")).not.toBe("true"));
  expect(within(dialog).getByText("Hemlig", { exact: true })).toBeTruthy();
  expect(within(dialog).getByText("Berörd assistent")).toBeTruthy();
  fireEvent.click(retry);
  expect(await screen.findByRole("switch", { name: "Efter klassning" })).toBeTruthy();
  expect(screen.queryByRole("switch", { name: "Före klassning" })).toBeNull();
  expect(api.PATCH).toHaveBeenCalledTimes(2);
  expect(api.PATCH.mock.calls.map(([, request]) => request.body)).toEqual([
    { security_classification: { id: "secret" } },
    { security_classification: { id: "secret" } }
  ]);
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
});
