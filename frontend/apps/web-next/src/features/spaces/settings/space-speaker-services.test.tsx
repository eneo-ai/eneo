// @vitest-environment jsdom
import { act, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { TranscriptionServiceSummary } from "@/features/admin/models/transcription-services";
import type { Space } from "../space";
import { makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown as Space }));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space, "space-1") };
});
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { SpaceSettings } from "./space-settings";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const failed = () =>
  Promise.resolve({ error: { message: "down" }, response: new Response("{}", { status: 503 }) });

const restricted = { id: "c2", name: "Skyddad", description: null, security_level: 3 };

const service = (
  id: string,
  name: string,
  overrides: Partial<TranscriptionServiceSummary> = {}
): TranscriptionServiceSummary => ({
  id,
  name,
  is_enabled: true,
  is_default: false,
  security_classification: null,
  ...overrides
});

const link = (id: string, name: string, meets = true, available = true) => ({
  id,
  name,
  meets_security_classification: meets,
  available,
  is_default: false
});

function show({
  services,
  space,
  securityEnabled = false
}: {
  services: TranscriptionServiceSummary[] | null;
  space: Partial<Space>;
  securityEnabled?: boolean;
}) {
  state.space = makeSpace({ overrides: space });
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/transcription-services/") {
      return services === null ? failed() : ok({ items: services, has_more: false });
    }
    if (path === "/api/v1/security-classifications/") {
      return ok({ security_enabled: securityEnabled, security_classifications: [restricted] });
    }
    if (path === "/api/v1/ai-models/") {
      return ok({ completion_models: [], embedding_models: [], transcription_models: [] });
    }
    return ok({ items: [] });
  });
  api.PATCH.mockImplementation((_path: string, request: { body: Record<string, unknown> }) => {
    const grants = request.body.transcription_services as { id: string }[] | undefined;
    state.space = {
      ...state.space,
      ...(grants && {
        transcription_services: grants.map(({ id }) => link(id, id))
      })
    } as Space;
    return ok(state.space);
  });
  const queryClient = testQueryClient();
  renderInApp(<SpaceSettings />, { queryClient });
  return queryClient;
}

const row = () => document.getElementById("speaker-services")!;
const toggle = (name: string) => within(row()).getByRole("switch", { name }) as HTMLInputElement;
const description = (element: HTMLElement) =>
  (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("explains why a granted service cannot be used, and keeps it removable", async () => {
  show({
    services: [
      service("low", "Vemsa Sundsvall"),
      service("off", "Vemsa Timrå", { is_enabled: false, security_classification: restricted })
    ],
    space: {
      security_classification: restricted,
      transcription_services: [
        link("low", "Vemsa Sundsvall", false, true),
        link("off", "Vemsa Timrå", true, false)
      ]
    },
    securityEnabled: true
  });

  const low = await waitFor(() => toggle("Vemsa Sundsvall"));
  expect(within(row()).getByText("Säkerhetsklassen är lägre än ytans.")).toBeTruthy();
  expect(within(row()).getByText("Avstängd av en administratör.")).toBeTruthy();
  expect(low.checked).toBe(true);
  expect(low.getAttribute("aria-disabled")).toBeNull();
  await act(async () => {
    await expectNoAxeViolations(row());
  });
});

it("says which service is the organisation's default, and that an ungranted one fills nothing in yet", async () => {
  show({
    services: [service("a", "Vemsa Sundsvall", { is_default: true }), service("b", "Vemsa Timrå")],
    space: { security_classification: null, transcription_services: [link("a", "Vemsa Sundsvall")] }
  });

  const sundsvall = await waitFor(() => toggle("Vemsa Sundsvall"));
  expect(description(sundsvall)).toContain(
    "Organisationens standard. Fylls i när ett flöde här börjar transkribera."
  );
  expect(description(toggle("Vemsa Timrå"))).not.toContain("Organisationens standard");
  cleanup();

  // The default the space has not been given says what giving it would do.
  show({
    services: [service("a", "Vemsa Sundsvall"), service("b", "Vemsa Timrå", { is_default: true })],
    space: { security_classification: null, transcription_services: [link("a", "Vemsa Sundsvall")] }
  });
  expect(description(await waitFor(() => toggle("Vemsa Timrå")))).toContain(
    "Organisationens standard. Ge ytan tillgång, så fylls den i när ett flöde här börjar transkribera."
  );
});

it("grants a usable service and refuses one below the space's classification", async () => {
  const queryClient = show({
    services: [
      service("kept", "Vemsa Härnösand", { security_classification: restricted }),
      service("low", "Vemsa Sundsvall"),
      service("new", "Vemsa Timrå", { security_classification: restricted })
    ],
    space: {
      security_classification: restricted,
      transcription_services: [link("kept", "Vemsa Härnösand")]
    },
    securityEnabled: true
  });

  const low = await waitFor(() => toggle("Vemsa Sundsvall"));
  expect(low.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(low);
  expect(api.PATCH).not.toHaveBeenCalled();

  fireEvent.click(toggle("Vemsa Timrå"));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledOnce());
  expect(api.PATCH.mock.calls[0]![1]).toEqual({
    params: { path: { id: "space-1" } },
    body: { transcription_services: [{ id: "kept" }, { id: "new" }] }
  });
  // The space the save returned is the one flows in the space read their services from.
  await waitFor(() => expect(toggle("Vemsa Timrå").checked).toBe(true));
  expect(
    queryClient
      .getQueryData<Space>(["spaces", "space-1"])
      ?.transcription_services?.map((granted) => granted.id)
  ).toEqual(["kept", "new"]);
});

it("removes a grant with the rest of the list kept", async () => {
  show({
    services: [service("a", "Vemsa Sundsvall"), service("b", "Vemsa Timrå")],
    space: {
      security_classification: null,
      transcription_services: [link("a", "Vemsa Sundsvall"), link("b", "Vemsa Timrå")]
    }
  });

  fireEvent.click(await waitFor(() => toggle("Vemsa Sundsvall")));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledOnce());
  expect(api.PATCH.mock.calls[0]![1].body).toEqual({ transcription_services: [{ id: "b" }] });
  await waitFor(() => expect(toggle("Vemsa Sundsvall").checked).toBe(false));
});

it("saves one change at a time: a press while a grant saves is ignored", async () => {
  show({
    services: [service("a", "Vemsa Sundsvall"), service("b", "Vemsa Timrå")],
    space: { security_classification: null, transcription_services: [] }
  });
  let answer: () => void = () => {};
  api.PATCH.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        answer = () => {
          state.space = { ...state.space, transcription_services: [link("a", "Vemsa Sundsvall")] };
          resolve({ data: state.space, response: new Response("{}") });
        };
      })
  );

  fireEvent.click(await waitFor(() => toggle("Vemsa Sundsvall")));
  // Busy, not disabled: the pressed switch keeps its focus.
  await waitFor(() => expect(toggle("Vemsa Sundsvall").getAttribute("aria-busy")).toBe("true"));
  fireEvent.click(toggle("Vemsa Timrå"));
  expect(api.PATCH).toHaveBeenCalledOnce();

  await act(async () => answer());
  await waitFor(() => expect(toggle("Vemsa Sundsvall").checked).toBe(true));
  expect(toggle("Vemsa Timrå").checked).toBe(false);
});

it("shows the grant as it was when the save fails", async () => {
  show({
    services: [service("s1", "Vemsa Sundsvall")],
    space: { security_classification: null, transcription_services: [] }
  });
  api.PATCH.mockImplementationOnce(() => failed());

  fireEvent.click(await waitFor(() => toggle("Vemsa Sundsvall")));
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledOnce());

  await waitFor(() => expect(toggle("Vemsa Sundsvall").getAttribute("aria-disabled")).toBeNull());
  expect(toggle("Vemsa Sundsvall").checked).toBe(false);
  expect(toast.error).toHaveBeenCalled();
});

it("says so when the organisation's services could not be read", async () => {
  show({ services: null, space: { security_classification: null, transcription_services: [] } });

  expect(
    await within(row()).findByText("Ytans tjänster för ordtider och talare kunde inte läsas in.")
  ).toBeTruthy();
  expect(within(row()).getByRole("alert")).toBeTruthy();
  expect(within(row()).queryByRole("switch")).toBeNull();
});

it("offers no grant when the space came without its granted services", async () => {
  show({ services: [service("s1", "Vemsa Sundsvall")], space: { security_classification: null } });

  expect(
    await within(row()).findByText("Ytans tjänster för ordtider och talare kunde inte läsas in.")
  ).toBeTruthy();
  expect(within(row()).queryByRole("switch")).toBeNull();
});
