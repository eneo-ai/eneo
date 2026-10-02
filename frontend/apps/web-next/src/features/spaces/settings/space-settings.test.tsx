// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "../space";
import { makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown as Space, routeId: "space-1" }));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space, state.routeId) };
});
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { SpaceSettings } from "./space-settings";

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response("{}") });
}

function deferredPatch() {
  let resolve!: (space: Space) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<{ data: Space; response: Response }>((success, failure) => {
    resolve = (space) => success({ data: space, response: new Response("{}") });
    reject = failure;
  });
  return { promise, resolve, reject };
}

function withCompletionModels(ids: string[]) {
  return makeSpace({
    overrides: {
      ...state.space,
      completion_models: ids.map((id) => ({ id, name: id, nickname: null }))
    }
  });
}

const availableModels = [
  { id: "north-1", name: "Aurora", org: "Nord AI", is_org_enabled: true, is_deprecated: false },
  { id: "north-2", name: "Borealis", org: "Nord AI", is_org_enabled: true, is_deprecated: false }
];

function showSettings(
  failOnceOn?: string,
  models: typeof availableModels = [],
  embeddingModels: typeof availableModels = [],
  routeId = "space-1",
  space?: Space
) {
  state.routeId = routeId;
  state.space =
    space ??
    makeSpace({
      overrides: { data_retention_days: 30, completion_models: [], embedding_models: [] }
    });
  const failed = new Set<string>();
  api.GET.mockImplementation((path: string) => {
    if (path === failOnceOn && !failed.has(path)) {
      failed.add(path);
      return Promise.resolve({
        error: { message: "Temporary failure" },
        response: new Response("{}", { status: 503 })
      });
    }
    if (path === "/api/v1/security-classifications/") {
      return ok({ security_enabled: false, security_classifications: [] });
    }
    if (path === "/api/v1/ai-models/") {
      return ok({
        completion_models: models,
        embedding_models: embeddingModels,
        transcription_models: []
      });
    }
    return ok({ items: [] });
  });
  api.PATCH.mockImplementation((_path: string, request: { body: Record<string, unknown> }) => {
    state.space = { ...state.space, ...request.body } as Space;
    return ok(state.space);
  });
  return renderInApp(<SpaceSettings />);
}

afterEach(() => {
  cleanup();
  api.GET.mockReset();
  api.PATCH.mockReset();
});

/** The model switches sit behind each card's "choose" button. */
async function openModels(kind: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Välj ${kind}` }));
}

it("offers section links and keeps each model type separate from tools", () => {
  showSettings();

  const navigation = screen.getByRole("navigation", { name: "Inställningar" });
  for (const name of [
    "Allmänt",
    "Säkerhet & Integritet",
    "Modeller",
    "Verktyg och anslutningar",
    "Funktioner",
    "API-nycklar",
    "Farozon"
  ]) {
    const link = within(navigation).getByRole("link", { name });
    const id = link.getAttribute("href")?.slice(1);
    expect(id).toBeTruthy();
    expect(document.getElementById(id!)).toBeTruthy();
  }
  const models = document.getElementById("models")!;
  expect(within(models).queryByText("MCP-servrar")).toBeNull();
  expect(
    within(document.getElementById("tools")!).getAllByText("MCP-servrar").length
  ).toBeGreaterThan(0);
});

it("lists each model type in the models section once the models have loaded", async () => {
  showSettings(undefined, availableModels);

  const models = document.getElementById("models")!;
  expect(await within(models).findByRole("heading", { name: "Chattmodeller" })).toBeTruthy();
  expect(within(models).getByRole("heading", { name: "Inbäddningsmodeller" })).toBeTruthy();
  expect(within(models).getByRole("heading", { name: "Transkriptionsmodeller" })).toBeTruthy();
});

it("shows organization settings without personal space sections", () => {
  showSettings(undefined, [], [], "space-1", makeSpace({ overrides: { organization: true } }));

  const navigation = screen.getByRole("navigation", { name: "Inställningar" });
  expect(within(navigation).queryByRole("link", { name: "Allmänt" })).toBeNull();
  expect(within(navigation).queryByRole("link", { name: "Säkerhet & Integritet" })).toBeNull();
  expect(within(navigation).queryByRole("link", { name: "Funktioner" })).toBeNull();
  expect(within(navigation).queryByRole("link", { name: "Farozon" })).toBeNull();
  expect(within(navigation).getByRole("link", { name: "Modeller" })).toBeTruthy();
  expect(within(navigation).getByRole("link", { name: "Verktyg och anslutningar" })).toBeTruthy();
});

it("keeps an empty space name and explains the error at the field until corrected", async () => {
  const { container } = showSettings();
  const name = screen.getByRole("textbox", { name: "Namn" });

  fireEvent.change(name, { target: { value: "  " } });
  fireEvent.blur(name);

  expect((name as HTMLInputElement).value).toBe("");
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByText(/Ange ett namn på ytan/)).toBeTruthy();
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);

  fireEvent.change(name, { target: { value: "Ny yta" } });
  fireEvent.blur(name);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { name: "Ny yta" }
    })
  );
  expect(name.getAttribute("aria-invalid")).toBeNull();
});

it("keeps invalid retention input, explains the allowed format and saves a correction", async () => {
  const { container } = showSettings();
  const retention = screen.getByRole("textbox", { name: "Gallring av konversationshistorik" });

  fireEvent.change(retention, { target: { value: "1.5" } });
  fireEvent.blur(retention);

  expect((retention as HTMLInputElement).value).toBe("1.5");
  expect(retention.getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByText(/Ange ett helt antal dagar större än noll/)).toBeTruthy();
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);

  fireEvent.change(retention, { target: { value: "14" } });
  fireEvent.blur(retention);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { data_retention_days: 14 }
    })
  );
  expect(retention.getAttribute("aria-invalid")).toBeNull();
});

it("shows the retention policy read-only to someone who may not edit the space", async () => {
  const { container } = showSettings(
    undefined,
    [],
    [],
    "space-1",
    makeSpace({
      permissions: ["read"],
      overrides: { data_retention_days: 30, completion_models: [], embedding_models: [] }
    })
  );
  const retention = screen.getByRole("textbox", { name: "Gallring av konversationshistorik" });

  expect((retention as HTMLInputElement).value).toBe("30");
  expect(retention.hasAttribute("disabled")).toBe(true);
  const hint = screen.getByText("Endast administratörer för utrymmet kan ändra gallringen.");
  expect(retention.getAttribute("aria-describedby")).toContain(hint.id);
  await expectNoAxeViolations(container);
});

it.each([
  ["/api/v1/security-classifications/", "Kunde inte läsa in säkerhetsklassningar för ytan."],
  ["/api/v1/ai-models/", "Kunde inte läsa in modeller för ytan."],
  ["/api/v1/mcp-servers/settings/", "Kunde inte läsa in MCP-servrar för ytan."]
])("explains a failed settings request and recovers with retry: %s", async (path, message) => {
  showSettings(path);

  expect(await screen.findByText(message)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /^Försök igen:/ }));

  await waitFor(() => expect(screen.queryByText(message)).toBeNull());
  expect(api.GET.mock.calls.filter(([calledPath]) => calledPath === path)).toHaveLength(2);
});

it("shows rapid model selections immediately and saves the latest intent in order", async () => {
  const { queryClient } = showSettings(undefined, availableModels);
  const first = deferredPatch();
  api.PATCH.mockReturnValueOnce(first.promise);
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });
  const borealis = screen.getByRole("switch", { name: "Borealis" });

  fireEvent.click(aurora);
  expect(aurora.getAttribute("data-state")).toBe("checked");
  expect(screen.getByText("1 / 2")).toBeTruthy();
  fireEvent.click(borealis);
  expect(borealis.getAttribute("data-state")).toBe("checked");
  expect(screen.getByText("2 / 2")).toBeTruthy();
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));

  state.space = withCompletionModels(["north-1"]);
  act(() => first.resolve(state.space));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]?.[1]?.body).toEqual({
    completion_models: [{ id: "north-1" }, { id: "north-2" }]
  });
  await waitFor(() =>
    expect(
      (queryClient.getQueryData<Space>(["spaces", "space-1"])?.completion_models ?? []).map(
        (model) => model.id
      )
    ).toEqual(["north-1", "north-2"])
  );
  expect(aurora.getAttribute("data-state")).toBe("checked");
  expect(borealis.getAttribute("data-state")).toBe("checked");
  expect(queryClient.getQueryData<Space>(["spaces", "space-1"])?.name).toBe("Upphandling");
});

it("keeps a second rapid toggle and restores the final off state", async () => {
  showSettings(undefined, availableModels);
  const first = deferredPatch();
  api.PATCH.mockReturnValueOnce(first.promise);
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });

  fireEvent.click(aurora);
  fireEvent.click(aurora);
  expect(aurora.getAttribute("data-state")).toBe("unchecked");
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));

  state.space = withCompletionModels(["north-1"]);
  act(() => first.resolve(state.space));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]?.[1]?.body).toEqual({ completion_models: [] });
  await waitFor(() => expect(aurora.getAttribute("data-state")).toBe("unchecked"));
});

it("serializes changes across model types without losing either selection", async () => {
  const { queryClient } = showSettings(undefined, availableModels, [
    {
      id: "embed-2",
      name: "Vector",
      org: "Nord AI",
      is_org_enabled: true,
      is_deprecated: false
    }
  ]);
  const first = deferredPatch();
  api.PATCH.mockReturnValueOnce(first.promise);
  await openModels("Chattmodeller");
  await openModels("Inbäddningsmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });
  const vector = screen.getByRole("switch", { name: "Vector" });

  fireEvent.click(aurora);
  fireEvent.click(vector);
  expect(aurora.getAttribute("data-state")).toBe("checked");
  expect(vector.getAttribute("data-state")).toBe("checked");
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));

  state.space = withCompletionModels(["north-1"]);
  act(() => first.resolve(state.space));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]?.[1]?.body).toEqual({ embedding_models: [{ id: "embed-2" }] });
  await waitFor(() => {
    const saved = queryClient.getQueryData<Space>(["spaces", "space-1"]);
    expect(saved?.completion_models.map((model) => model.id)).toEqual(["north-1"]);
    expect(saved?.embedding_models.map((model) => model.id)).toEqual(["embed-2"]);
  });
});

it("adopts the server's normalized selection without saving in a loop", async () => {
  showSettings(undefined, availableModels);
  const first = deferredPatch();
  api.PATCH.mockReturnValueOnce(first.promise);
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });

  fireEvent.click(aurora);
  expect(aurora.getAttribute("data-state")).toBe("checked");
  act(() => first.resolve(state.space));

  await waitFor(() => expect(aurora.getAttribute("data-state")).toBe("unchecked"));
  expect(api.PATCH).toHaveBeenCalledTimes(1);
});

it("keeps the PATCH response when an older detail fetch completes late", async () => {
  const { queryClient } = showSettings(undefined, availableModels);
  let resolveOldFetch!: (space: Space) => void;
  const oldFetchResult = new Promise<Space>((resolve) => {
    resolveOldFetch = resolve;
  });
  const oldFetch = queryClient
    .query({ queryKey: ["spaces", "space-1"], queryFn: () => oldFetchResult, staleTime: 0 })
    .catch(() => undefined);
  const accepted = withCompletionModels(["north-1"]);
  api.PATCH.mockReturnValueOnce(ok(accepted));
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });

  fireEvent.click(aurora);
  await waitFor(() =>
    expect(queryClient.getQueryData<Space>(["spaces", "space-1"])?.completion_models).toEqual(
      accepted.completion_models
    )
  );
  act(() => resolveOldFetch(state.space));
  await oldFetch;
  expect(queryClient.getQueryData<Space>(["spaces", "space-1"])?.completion_models).toEqual(
    accepted.completion_models
  );
});

it("updates the detail cache under a personal space route alias", async () => {
  const { queryClient } = showSettings(undefined, availableModels, [], "personal");
  const accepted = withCompletionModels(["north-1"]);
  api.PATCH.mockReturnValueOnce(ok(accepted));
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });

  fireEvent.click(aurora);

  await waitFor(() =>
    expect(queryClient.getQueryData<Space>(["spaces", "personal"])?.completion_models).toEqual(
      accepted.completion_models
    )
  );
  expect(queryClient.getQueryData(["spaces", "space-1"])).toBeUndefined();
});

it("rolls back only unsaved model selections and explains a failed save", async () => {
  showSettings(undefined, availableModels);
  const first = deferredPatch();
  api.PATCH.mockReturnValueOnce(first.promise).mockRejectedValueOnce(new Error("Network down"));
  await openModels("Chattmodeller");
  const aurora = await screen.findByRole("switch", { name: "Aurora" });
  const borealis = screen.getByRole("switch", { name: "Borealis" });

  fireEvent.click(aurora);
  fireEvent.click(borealis);
  state.space = withCompletionModels(["north-1"]);
  act(() => first.resolve(state.space));

  expect(await screen.findByText(/Modellvalen kunde inte sparas/)).toBeTruthy();
  expect(aurora.getAttribute("data-state")).toBe("checked");
  expect(borealis.getAttribute("data-state")).toBe("unchecked");
  expect(api.PATCH).toHaveBeenCalledTimes(2);
});
