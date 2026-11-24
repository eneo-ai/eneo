// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import type { Permission } from "@/lib/auth/permissions";
import { recordAnnouncements, renderInApp, testAppContext } from "@/test/render";
import { router } from "@/test/navigation";
import messages from "@/lib/i18n/messages/sv.json";
import { setViewport } from "@/test/setup-dom";
import { TRANSCRIPTION_SERVICE_CATALOGUE_KEY } from "@/features/admin/models/transcription-services";
import { spaceQueryOptions, type Space } from "../space";
import { makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown as Space, routeId: "space-1" }));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space, state.routeId) };
});
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", async (importOriginal) => {
  const { toast } = await importOriginal<typeof import("@/lib/toast")>();
  return { toast: { ...toast, error: toastError } };
});

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
  space?: Space,
  permissions: Permission[] = ["retention_manage"]
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
    // The space as the server has it now: the retention field reads it before it decides.
    if (path === "/api/v1/spaces/{id}/" || path.startsWith("/api/v1/spaces/type/")) {
      return ok(state.space);
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
  return renderInApp(<SpaceSettings />, { appContext: testAppContext({ permissions }) });
}

afterEach(() => {
  cleanup();
  api.GET.mockReset();
  api.PATCH.mockReset();
  api.DELETE.mockReset();
  toastError.mockReset();
});

/** The strip of section links (a phone's index is another navigation of the same name). */
function sectionLinks() {
  const strip = screen
    .getAllByRole("navigation", { name: "Inställningar" })
    .find((navigation) => navigation.querySelector("a[href^='#']"));
  if (!strip) throw new Error("No strip of section links");
  return strip;
}

/** The model switches sit behind each card's "choose" button. */
async function openModels(kind: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Välj modeller, ${kind}` }));
}

it("offers section links and keeps each model type separate from tools", () => {
  showSettings();

  const navigation = sectionLinks();
  for (const name of [
    "Allmänt",
    "Säkerhet och integritet",
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

it("opens on a phone with an index of the sections, as the assistant editor does", async () => {
  setViewport("phone");
  const { container } = showSettings();

  const index = document.querySelector<HTMLElement>("[data-editor-index]")!;
  expect(document.querySelector("[data-editor-view]")?.getAttribute("data-editor-view")).toBe(
    "index"
  );
  const rows = within(index).getAllByRole("link");
  expect(rows.map((row) => row.getAttribute("href"))).toEqual([
    "/?section=general",
    "/?section=security",
    "/?section=models",
    "/?section=tools",
    "/?section=capabilities",
    "/?section=api-keys",
    "/?section=danger"
  ]);
  expect(
    within(index)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent)
  ).toEqual(["Ytan", "Modell och funktioner", "Åtkomst"]);
  // Deleting the space is not an access setting: it stands alone, last, under no heading.
  const lists = index.querySelectorAll("ul");
  expect(within(lists[lists.length - 1]!).getAllByRole("link")).toHaveLength(1);
  expect(within(lists[lists.length - 1]!).getByRole("link", { name: /Farozon/ })).toBeTruthy();
  expect(within(lists[lists.length - 2]!).queryByRole("link", { name: /Farozon/ })).toBeNull();
  // The space's page bar is above it: the index has none of its own, a section has one back to it.
  expect(container.querySelector("[data-phone-page-bar]")).toBeNull();
  // What the space holds is said on the row, so the index tells before it is opened.
  expect(rows[1]!.textContent).toMatch(/^Säkerhet och integritet, .*30/);
  // The index names itself (the frame's bar shows its title only after a scroll), under the
  // frame's h1, not beside it.
  const names = [...container.querySelectorAll(".wide\\:hidden > h2")].map(
    (heading) => heading.textContent
  );
  expect(names).toEqual(["Inställningar"]);
  expect(container.querySelector("h1")).toBeNull();
  await expectNoAxeViolations(container);
});

it("says nothing about a space's security while it keeps nothing back", () => {
  setViewport("phone");
  state.space = makeSpace({ overrides: { data_retention_days: null } });
  showSettings(undefined, [], [], "space-1", state.space);
  const rows = within(document.querySelector<HTMLElement>("[data-editor-index]")!).getAllByRole(
    "link"
  );
  expect(rows[1]!.textContent).toBe("Säkerhet och integritet");
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

  const navigation = sectionLinks();
  expect(within(navigation).queryByRole("link", { name: "Allmänt" })).toBeNull();
  expect(within(navigation).queryByRole("link", { name: "Säkerhet och integritet" })).toBeNull();
  expect(within(navigation).getByRole("link", { name: "Funktioner" })).toBeTruthy();
  const webSearch = within(document.getElementById("capabilities")!).getByRole("switch", {
    name: "Webbsökning"
  });
  expect(webSearch.hasAttribute("disabled")).toBe(true);
  expect(within(navigation).queryByRole("link", { name: "Farozon" })).toBeNull();
  expect(within(navigation).getByRole("link", { name: "Modeller" })).toBeTruthy();
  expect(within(navigation).getByRole("link", { name: "Verktyg och anslutningar" })).toBeTruthy();
});

it("saves an available organization capability through the existing space update", async () => {
  showSettings(
    undefined,
    [],
    [],
    "organization",
    makeSpace({
      overrides: {
        organization: true,
        enabled_capabilities: [],
        available_capabilities: [{ purpose: "web_search", available: true, reason: null }]
      }
    })
  );
  fireEvent.click(
    within(document.getElementById("capabilities")!).getByRole("switch", { name: "Webbsökning" })
  );
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { enabled_capabilities: ["web_search"] }
    })
  );
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
  const { container, queryClient } = showSettings();
  const retention = screen.getByRole("textbox", { name: "Gallringstid för ytan" });
  // The time covers flows too, and says that what is older goes for good.
  expect(screen.getByText(messages.space_retention_description)).toBeTruthy();
  queryClient.setQueryData(["flows", "detail", "flow-1"], { id: "flow-1" });

  fireEvent.change(retention, { target: { value: "1.5" } });
  fireEvent.blur(retention);

  expect((retention as HTMLInputElement).value).toBe("1.5");
  expect(retention.getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByText(/Ange ett helt antal dagar från 1 till 2555/)).toBeTruthy();
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);

  fireEvent.change(retention, { target: { value: "45" } });
  fireEvent.blur(retention);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { data_retention_days: 45, expected_data_retention_days: 30 }
    })
  );
  expect(retention.getAttribute("aria-invalid")).toBeNull();
  // The flows' effective times follow the new cap.
  await waitFor(() =>
    expect(queryClient.getQueryState(["flows", "detail", "flow-1"])?.isInvalidated).toBe(true)
  );
});

function retentionField() {
  return screen.getByRole("textbox", { name: "Gallringstid för ytan" }) as HTMLInputElement;
}

function enterRetention(value: string) {
  const field = retentionField();
  fireEvent.change(field, { target: { value } });
  fireEvent.blur(field);
  return field;
}

it.each([
  ["lengthens the time", 30, "60", 60],
  ["clears the time", 30, "", null]
])("%s without asking and says what applies from now", async (_, saved, typed, sent) => {
  const { container } = showSettings(
    undefined,
    [],
    [],
    "space-1",
    makeSpace({
      overrides: { data_retention_days: saved, completion_models: [], embedding_models: [] }
    })
  );
  const said = recordAnnouncements();
  enterRetention(typed);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { data_retention_days: sent, expected_data_retention_days: saved }
    })
  );
  expect(screen.queryByRole("alertdialog")).toBeNull();
  const note =
    sent === null
      ? messages.space_retention_saved_off
      : `Körningar i ytans flöden som startar medan ytan har en tid räknas som förfallna när de är äldre än ${sent} dagar, eller flödets kortare tid, och tas bort vid en kommande kontroll. Kontrollen görs var femte minut; en spärr, en kö eller ett lås kan fördröja borttagningen. Körningar som startade medan ytan saknade tid rörs inte.`;
  // Shown under the field and said once, politely, without moving the focus.
  const section = document.getElementById("security")!;
  expect(await within(section).findByText(note)).toBeTruthy();
  await waitFor(() => expect(said).toContain(note));
  await expectNoAxeViolations(container);
});

// A time that removes content asks first: one set on a space without a time, or a shorter one.
it.each([
  ["a time on a space without one", null, "7", "asks"],
  ["a shorter time", 30, "7", "asks"],
  ["a longer time", 30, "60", "saves"],
  ["a cleared time", 30, "", "saves"],
  ["the same time", 30, "30", "nothing"]
] as const)("decides on %s against the server's time", async (_, saved, typed, outcome) => {
  showSettings(
    undefined,
    [],
    [],
    "space-1",
    makeSpace({
      overrides: { data_retention_days: saved, completion_models: [], embedding_models: [] }
    })
  );
  const sent = typed === "" ? null : Number(typed);
  const body = {
    params: { path: { id: "space-1" } },
    body: { data_retention_days: sent, expected_data_retention_days: saved }
  };
  if (outcome === "nothing") {
    // The field shows this time already: another value first, so the typed one is a change.
    fireEvent.change(retentionField(), { target: { value: "45" } });
    enterRetention(typed);
    expect(retentionField().value).toBe(typed);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.PATCH).not.toHaveBeenCalled();
    return;
  }
  if (outcome === "saves") {
    enterRetention(typed);
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", body)
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    return;
  }
  enterRetention(typed);
  const title = { name: messages.space_retention_shorten_title };
  fireEvent.click(
    within(await screen.findByRole("alertdialog", title)).getByRole("button", { name: "Avbryt" })
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(retentionField().value).toBe(saved === null ? "" : String(saved));
  enterRetention(typed);
  const dialog = await screen.findByRole("alertdialog", title);
  expect(api.PATCH).not.toHaveBeenCalled();
  fireEvent.click(
    within(dialog).getByRole("button", { name: messages.space_retention_shorten_confirm })
  );
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", body)
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(retentionField().value).toBe(typed);
});

it("promises nothing about flow runs in a personal space", async () => {
  showSettings(
    undefined,
    [],
    [],
    "personal",
    makeSpace({
      permissions: ["read", "edit"],
      overrides: {
        personal: true,
        data_retention_days: 30,
        completion_models: [],
        embedding_models: []
      }
    })
  );
  const section = document.getElementById("security")!;
  expect(
    within(section).getByText(
      "Gäller assistenter och appar i ytan som inte har en egen tid. Det som har passerat tiden räknas som förfallet och tas bort vid en kommande kontroll. Det går inte att återställa."
    )
  ).toBeTruthy();
  enterRetention("45");
  expect(
    await within(section).findByText(
      "Sparat. Assistenter och appar i ytan utan egen tid följer nu 45 dagar."
    )
  ).toBeTruthy();
  expect(within(section).queryByText(/flöden/)).toBeNull();
});

it("asks before a shorter time is saved and saves it once confirmed", async () => {
  showSettings();
  enterRetention("7");
  const dialog = await screen.findByRole("alertdialog", { name: "Spara gallringstiden?" });
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(
    within(dialog).getByText(
      "Innehåll som följer ytans tid och redan är äldre än 7 dagar räknas som förfallet och tas bort vid en kommande kontroll. Det går inte att återställa."
    )
  ).toBeTruthy();
  // The least destructive choice has the focus.
  expect(
    within(dialog).getByRole("button", { name: "Avbryt" }).hasAttribute("data-autofocus")
  ).toBe(true);
  await expectNoAxeViolations(dialog);

  fireEvent.click(within(dialog).getByRole("button", { name: "Spara tiden" }));
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { data_retention_days: 7, expected_data_retention_days: 30 }
    })
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(retentionField().value).toBe("7");
  expect(
    await within(document.getElementById("security")!).findByText(
      /äldre än 7 dagar, eller flödets kortare tid/
    )
  ).toBeTruthy();
});

it.each([
  [
    "Cancel",
    (dialog: HTMLElement) => fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }))
  ],
  ["Escape", (dialog: HTMLElement) => fireEvent.keyDown(dialog, { key: "Escape" })]
])("restores the saved time when a shorter one is not confirmed (%s)", async (_, dismiss) => {
  showSettings();
  enterRetention("7");
  dismiss(await screen.findByRole("alertdialog"));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(retentionField().value).toBe("30");
  expect(api.PATCH).not.toHaveBeenCalled();
});

/** Answers a space save as the server does: refused while the time it carries is out of date. */
function answerSavesAsServer() {
  api.PATCH.mockImplementation((_path: string, request: { body: Record<string, unknown> }) => {
    const { expected_data_retention_days: expected, ...change } = request.body;
    if (
      "data_retention_days" in change &&
      expected !== undefined &&
      expected !== state.space.data_retention_days
    ) {
      return Promise.resolve({
        error: {
          message: "The retention time has changed.",
          code: "retention_time_changed",
          eneo_error_code: 9087,
          context: { current_days: state.space.data_retention_days }
        },
        response: new Response("{}", { status: 409 })
      });
    }
    state.space = { ...state.space, ...change } as Space;
    return ok(state.space);
  });
}

it("saves nothing when another administrator changed the time, and decides the next try on the new time", async () => {
  showSettings();
  answerSavesAsServer();
  // Another administrator lengthened the time after this page read 30.
  state.space = { ...state.space, data_retention_days: 90 };
  // Longer than the 30 the page has: saved at once, with the time it was compared with.
  const field = enterRetention("60");
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { data_retention_days: 60, expected_data_retention_days: 30 }
    })
  );
  // Said once, in a short line: the time changed, check it and save again.
  await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
  expect(toastError.mock.calls[0]![0]).toBe(messages.eneo_error_9087);
  expect(state.space.data_retention_days).toBe(90);
  // The draft stays while the page reads the space again.
  await waitFor(() => expect(field.readOnly).toBe(false));
  expect(field.value).toBe("60");
  expect(screen.queryByText(/äldre än 60 dagar/)).toBeNull();

  // The next try is decided on the 90 read: 60 is shorter, so it asks first.
  fireEvent.blur(field);
  const dialog = await screen.findByRole("alertdialog", { name: "Spara gallringstiden?" });
  expect(api.PATCH).toHaveBeenCalledTimes(1);
  fireEvent.click(
    within(dialog).getByRole("button", { name: messages.space_retention_shorten_confirm })
  );
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]![1].body).toEqual({
    data_retention_days: 60,
    expected_data_retention_days: 90
  });
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(state.space.data_retention_days).toBe(60);
});

it("closes the confirmation and keeps the typed time when the time changed before it was confirmed", async () => {
  showSettings();
  answerSavesAsServer();
  const field = enterRetention("7");
  const title = { name: "Spara gallringstiden?" };
  const dialog = await screen.findByRole("alertdialog", title);
  // Another administrator shortened the time while the dialog was open.
  state.space = { ...state.space, data_retention_days: 10 };
  fireEvent.click(
    within(dialog).getByRole("button", { name: messages.space_retention_shorten_confirm })
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.PATCH.mock.calls[0]![1].body).toEqual({
    data_retention_days: 7,
    expected_data_retention_days: 30
  });
  expect(state.space.data_retention_days).toBe(10);
  expect(field.value).toBe("7");
  // Decided again on the 10 read, not sent again with the 30 it was compared with.
  await waitFor(() => expect(retentionField().readOnly).toBe(false));
  fireEvent.blur(field);
  expect(await screen.findByRole("alertdialog", title)).toBeTruthy();
  expect(api.PATCH).toHaveBeenCalledTimes(1);
});

/** Space reads from here on, and a hook to hold the next one. */
function countSpaceReads() {
  const reads = api.GET.getMockImplementation()!;
  const counted = { reads: 0, hold: null as null | { answer: Promise<unknown> } };
  api.GET.mockImplementation((path: string, init: unknown) => {
    if (path !== "/api/v1/spaces/{id}/") return reads(path, init);
    counted.reads += 1;
    const held = counted.hold;
    counted.hold = null;
    return held ? held.answer : reads(path, init);
  });
  return counted;
}

/** The page with speaker service A granted and A, B and C to choose from. */
async function showSettingsWithGrants() {
  const grant = (id: string) => ({
    id,
    name: id,
    meets_security_classification: true,
    available: true,
    is_default: false
  });
  const shown = showSettings(
    undefined,
    [],
    [],
    "space-1",
    makeSpace({
      overrides: {
        data_retention_days: 30,
        completion_models: [],
        embedding_models: [],
        transcription_services: [grant("A")]
      }
    })
  );
  const reads = api.GET.getMockImplementation()!;
  api.GET.mockImplementation((path: string, init: unknown) =>
    path === "/api/v1/transcription-services/"
      ? ok({
          items: ["A", "B", "C"].map((id) => ({
            id,
            name: id,
            is_enabled: true,
            is_default: false,
            security_classification: null
          }))
        })
      : reads(path, init)
  );
  await screen.findByText(messages.speaker_service_empty_title);
  await act(() =>
    shown.queryClient.refetchQueries({ queryKey: TRANSCRIPTION_SERVICE_CATALOGUE_KEY })
  );
  api.PATCH.mockImplementation((_path: string, request: { body: Record<string, unknown> }) => {
    const { transcription_services, ...change } = request.body as {
      transcription_services?: { id: string }[];
    } & Record<string, unknown>;
    delete change.expected_data_retention_days;
    state.space = {
      ...state.space,
      ...change,
      ...(transcription_services
        ? { transcription_services: transcription_services.map(({ id }) => grant(id)) }
        : {})
    } as Space;
    return ok(state.space);
  });
  return { ...shown, grant };
}

it("keeps a grant saved on the page before and while the time is saved, so the next save sends it too", async () => {
  await showSettingsWithGrants();
  // B's save is on its way when the time is changed; the time's save waits for it.
  const patch = deferredPatch();
  const saveB = api.PATCH.getMockImplementation()!;
  api.PATCH.mockImplementationOnce((path: string, request: unknown) =>
    saveB(path, request).then(() => patch.promise)
  );
  fireEvent.click(await screen.findByRole("switch", { name: "B" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  enterRetention("60");
  await act(async () => patch.resolve(state.space));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]![1].body).toEqual({
    data_retention_days: 60,
    expected_data_retention_days: 30
  });
  await waitFor(() => expect(retentionField().readOnly).toBe(false));
  // After the time: C, built from the space the last save returned.
  fireEvent.click(screen.getByRole("switch", { name: "C" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(3));
  expect(api.PATCH.mock.calls[2]![1].body).toEqual({
    transcription_services: [{ id: "A" }, { id: "B" }, { id: "C" }]
  });
});

it("keeps a grant another tab saved, which a refresh on its way brings, so the next save sends it too", async () => {
  const { queryClient, grant } = await showSettingsWithGrants();
  // Another tab granted B; the page's ordinary refresh that brings it is on its way.
  state.space = { ...state.space, transcription_services: [grant("A"), grant("B")] };
  const counted = countSpaceReads();
  let answer!: (value: unknown) => void;
  counted.hold = { answer: new Promise((resolve) => (answer = resolve)) };
  void queryClient
    .query({ ...spaceQueryOptions(api as never, "space-1"), staleTime: 0 })
    .catch(() => {});
  await waitFor(() => expect(counted.reads).toBe(1));
  enterRetention("7");
  const dialog = await screen.findByRole("alertdialog", { name: "Spara gallringstiden?" });
  await act(async () => answer({ data: state.space, response: new Response("{}") }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  // The field neither read the space nor stopped the page's own read.
  expect(counted.reads).toBe(1);
  fireEvent.click(await screen.findByRole("switch", { name: "C" }));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  expect(api.PATCH.mock.calls[0]![1].body).toEqual({
    transcription_services: [{ id: "A" }, { id: "B" }, { id: "C" }]
  });
});

it("keeps the field read-only while a time is saved, so a clear made after it is not lost", async () => {
  showSettings();
  const patch = deferredPatch();
  api.PATCH.mockReturnValueOnce(patch.promise);
  const field = enterRetention("45");
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
  // A second change cannot be typed while the first is on its way.
  expect(field.readOnly).toBe(true);
  await act(async () => {
    state.space = { ...state.space, data_retention_days: 45 };
    patch.resolve(state.space);
  });
  await waitFor(() => expect(field.readOnly).toBe(false));
  enterRetention("");
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH.mock.calls[1]![1].body).toEqual({
    data_retention_days: null,
    expected_data_retention_days: 45
  });
});

it("puts the focus back on the field when a shorter time is not confirmed, also after a click elsewhere", async () => {
  showSettings();
  const field = retentionField();
  field.focus();
  fireEvent.change(field, { target: { value: "7" } });
  // A click on nothing focusable: the focus leaves the field for the page.
  field.blur();
  expect(document.activeElement).toBe(document.body);
  fireEvent.blur(field);
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(field));
});

it("never sends an unconfirmed shorter time when the page is left", async () => {
  const { unmount } = showSettings();
  fireEvent.change(retentionField(), { target: { value: "7" } });
  unmount();
  await act(async () => {});
  expect(api.PATCH).not.toHaveBeenCalled();
});

it("asks a space admin without retention_manage for the permission and keeps the time read-only", async () => {
  const { container } = showSettings(undefined, [], [], "space-1", undefined, []);
  const retention = screen.getByRole("textbox", { name: "Gallringstid för ytan" });
  expect(retention.hasAttribute("disabled")).toBe(true);
  const hint = screen.getByText(
    "För att ändra tiden krävs behörigheten Gallring – hantera regler. En administratör ger den till en roll."
  );
  expect(retention.getAttribute("aria-describedby")).toContain(hint.id);
  // The rest of the space stays editable.
  expect(screen.getByRole("textbox", { name: "Namn" }).hasAttribute("disabled")).toBe(false);
  await expectNoAxeViolations(container);
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
  const retention = screen.getByRole("textbox", { name: "Gallringstid för ytan" });

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

it("keeps a saved deprecated model visible in the space model selector", async () => {
  const deprecated = {
    ...availableModels[0]!,
    is_deprecated: true,
    deprecation_date: "2020-01-01"
  };
  showSettings(
    undefined,
    [deprecated],
    [],
    "space-1",
    makeSpace({ overrides: { completion_models: [{ id: "north-1", name: "Aurora" }] } })
  );
  await openModels("Chattmodeller");
  const selected = await screen.findByRole("switch", { name: "Aurora" });
  expect(selected.getAttribute("aria-checked")).toBe("true");
  fireEvent.click(selected);
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
      params: { path: { id: "space-1" } },
      body: { completion_models: [] }
    })
  );
});

it("shows and clears the same delayed deletion hint from space settings", async () => {
  let finish!: (value: unknown) => void;
  api.DELETE.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  showSettings();
  fireEvent.click(screen.getByRole("button", { name: messages.delete_this_space }));
  const dialog = await screen.findByRole("alertdialog", { name: messages.delete_space });
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: messages.enter_space_name_to_confirm }),
    { target: { value: state.space.name } }
  );
  vi.useFakeTimers();
  try {
    fireEvent.click(within(dialog).getByRole("button", { name: messages.confirm_deletion }));
    await act(async () => vi.advanceTimersByTimeAsync(4999));
    expect(within(dialog).queryByText(messages.delete_space_hint)).toBeNull();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(within(dialog).getByText(messages.delete_space_hint)).toBeTruthy();
    await act(async () => {
      finish({ data: null, response: new Response(null, { status: 204 }) });
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.queryByText(messages.delete_space_hint)).toBeNull();
    expect(router.push).toHaveBeenCalledExactlyOnceWith("/spaces/list");
  } finally {
    vi.useRealTimers();
  }
});

it("refreshes the list after a delete and never reads the deleted space again", async () => {
  api.DELETE.mockResolvedValue({ data: null, response: new Response(null, { status: 204 }) });
  const { queryClient } = showSettings();
  const space = ["spaces", "space-1"];
  const applications = ["spaces", "space-1", "applications"];
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(applications, {});
  const reads = queryClient.getQueryState(space)!.dataUpdateCount;
  // A read of the space that started before the delete answers after it.
  let answerLate!: (space: Space) => void;
  const lateRead = queryClient
    .query({
      queryKey: space,
      queryFn: () => new Promise<Space>((resolve) => (answerLate = resolve)),
      staleTime: 0
    })
    .catch(() => undefined);

  fireEvent.click(screen.getByRole("button", { name: messages.delete_this_space }));
  const dialog = await screen.findByRole("alertdialog", { name: messages.delete_space });
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: messages.enter_space_name_to_confirm }),
    { target: { value: state.space.name } }
  );
  fireEvent.click(within(dialog).getByRole("button", { name: messages.confirm_deletion }));

  await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/list"));
  answerLate(state.space);
  await act(() => lateRead);
  expect(api.DELETE).toHaveBeenCalledWith("/api/v1/spaces/{id}/", {
    params: { path: { id: "space-1" } }
  });
  expect(queryClient.getQueryState(["spaces"])?.isInvalidated).toBe(true);
  // Coming back to it reads it again; nothing reads it now.
  expect(queryClient.getQueryState(space)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(applications)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(space)?.dataUpdateCount).toBe(reads);
  expect(queryClient.getQueryState(space)?.fetchStatus).toBe("idle");
  expect(queryClient.getQueryCache().find({ queryKey: space, exact: true })?.isStale()).toBe(true);
});
