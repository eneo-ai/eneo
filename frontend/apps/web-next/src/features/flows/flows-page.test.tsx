// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { replaceUrl, router } from "@/test/navigation";
import type { Permission } from "@/lib/auth/permissions";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { flowPermissions, makeFlow } from "./flow-fixtures";
import { flowKeys, type FlowSparse } from "./flows-api";
import messages from "@/lib/i18n/messages/sv.json";
import { FlowsPage } from "./flows-page";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const sparse = (overrides: Partial<FlowSparse>): FlowSparse => {
  const flow: Partial<ReturnType<typeof makeFlow>> = makeFlow();
  delete flow.steps;
  return { ...(flow as FlowSparse), ...overrides };
};

const LIST = "/spaces/space-1/flows";

function renderPage(
  flows: FlowSparse[],
  permissions: Permission[] = ["flows_view", "flows_manage"],
  route = LIST
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(
    ["spaces", "space-1"],
    makeSpace({
      members: [{ id: "user-2", username: "anna.lind", email: "anna@kommun.se", role: "editor" }]
    })
  );
  queryClient.setQueryData(flowKeys.list("space-1"), flows);
  return renderInApp(<FlowsPage />, {
    queryClient,
    appContext: testAppContext({ permissions }),
    route
  });
}

/** Three flows the API returns oldest first; the viewer is user-1. */
const dated = () => [
  sparse({
    id: "letter",
    name: "Medborgarbrev",
    description: "Sammanfattar och besvarar brev.",
    published_version: 2,
    updated_at: "2026-08-04T13:40:00Z",
    owner_user_id: "user-1"
  }),
  sparse({
    id: "minutes",
    name: "Mötesprotokoll",
    description: "Skriver ut mötet.",
    input_type: "audio",
    output_type: "docx",
    updated_at: "2026-08-16T09:52:00Z",
    owner_user_id: null,
    created_by_user_id: "user-2"
  }),
  sparse({
    id: "consultation",
    name: "Remissvar",
    description: null,
    updated_at: "2026-08-10T09:00:00Z",
    owner_user_id: "user-9"
  })
];

const search = () => screen.getByLabelText("Sök flöden");
const NAMES = ["Medborgarbrev", "Mötesprotokoll", "Remissvar"];
/** The names of the flows shown, in order, in the table or the phone rows. */
const shown = () =>
  screen
    .queryAllByRole("link")
    .map((link) => NAMES.find((name) => link.textContent?.startsWith(name)))
    .filter(Boolean);

describe("FlowsPage", () => {
  it("lists the space's flows with their state and links to each", async () => {
    const { container } = renderPage([
      sparse({ id: "f1", name: "Medborgarbrev", published_version: 2, step_count: 3 }),
      sparse({ id: "f2", name: "Remissvar", description: null, step_count: 1 })
    ]);
    const table = screen.getByRole("table", { name: "Flöden" });
    const link = within(table).getByRole("link", { name: "Medborgarbrev" });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/f1");
    expect(within(table).getByText("Publicerad, version 2")).toBeTruthy();
    expect(within(table).getByText("Utkast")).toBeTruthy();
    expect(within(table).getByText("3 steg")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("lists the last changed flow first and says how many there are", async () => {
    const { container } = renderPage(dated());
    expect(shown()).toEqual(["Mötesprotokoll", "Remissvar", "Medborgarbrev"]);
    expect(screen.getByText("3 flöden · sorterade efter senast ändrad")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("says whose each flow is, by the names the space's members go by", async () => {
    const { container } = renderPage(dated());
    const table = screen.getByRole("table", { name: "Flöden" });
    expect(within(table).getByRole("columnheader", { name: "Ägare" })).toBeTruthy();
    const row = (name: string) => within(table).getByRole("link", { name }).closest("tr")!;
    // Nobody took it over: it is its creator's.
    expect(within(row("Mötesprotokoll")).getByText("anna.lind")).toBeTruthy();
    expect(within(row("Medborgarbrev")).getByText("Du")).toBeTruthy();
    expect(within(row("Remissvar")).getByText("Okänd")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("finds a flow by its name, description or what it takes in, and keeps the search in the address", async () => {
    renderPage(dated());
    fireEvent.change(search(), { target: { value: "LJUD" } });
    expect(shown()).toEqual(["Mötesprotokoll"]);
    expect(screen.getByText("1 flöde · sorterat efter senast ändrad")).toBeTruthy();
    fireEvent.change(search(), { target: { value: "besvarar" } });
    expect(shown()).toEqual(["Medborgarbrev"]);
    await waitFor(() => expect(replaceUrl).toHaveBeenLastCalledWith(`${LIST}?q=besvarar`));
  });

  it("filters published flows and drafts, and keeps the choice in the address", () => {
    renderPage(dated());
    fireEvent.click(screen.getByRole("radio", { name: "Utkast" }));
    expect(replaceUrl).toHaveBeenLastCalledWith(`${LIST}?status=drafts`);
    expect(shown()).toEqual(["Mötesprotokoll", "Remissvar"]);
    fireEvent.click(screen.getByRole("radio", { name: "Publicerade" }));
    expect(shown()).toEqual(["Medborgarbrev"]);
    fireEvent.click(screen.getByRole("radio", { name: "Alla" }));
    expect(replaceUrl).toHaveBeenLastCalledWith(LIST);
    expect(shown()).toHaveLength(3);
  });

  it("opens with the search and filter the address holds", () => {
    renderPage(dated(), undefined, `${LIST}?q=protokoll&status=drafts`);
    expect(search()).toHaveProperty("value", "protokoll");
    expect(screen.getByRole("radio", { name: "Utkast" }).getAttribute("aria-checked")).toBe("true");
    expect(shown()).toEqual(["Mötesprotokoll"]);
  });

  it("says when no flow matches, then clears the search or shows every state again", async () => {
    const { container } = renderPage(dated(), undefined, `${LIST}?q=finns-inte`);
    expect(screen.getByRole("heading", { name: "Inga flöden matchar din sökning" })).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Rensa sökningen" }));
    expect(document.activeElement).toBe(search());
    expect(search()).toHaveProperty("value", "");
    expect(shown()).toHaveLength(3);
    cleanup();

    renderPage([dated()[1]!], undefined, `${LIST}?status=published`);
    expect(screen.getByRole("heading", { name: "Inga publicerade flöden än" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visa alla" }));
    expect(replaceUrl).toHaveBeenLastCalledWith(LIST);
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Alla" }));
    expect(shown()).toEqual(["Mötesprotokoll"]);
    cleanup();

    renderPage([dated()[0]!], undefined, `${LIST}?status=drafts`);
    expect(screen.getByRole("heading", { name: "Inga utkast just nu" })).toBeTruthy();
  });

  it("offers the state filter only to those who manage flows, and ignores one in the address for others", () => {
    renderPage(dated(), ["flows_view"], `${LIST}?status=drafts`);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(search()).toBeTruthy();
    expect(shown()).toHaveLength(3);
  });

  it("offers a first flow when the space has none, and only to those who manage flows", () => {
    renderPage([]);
    expect(screen.getByRole("heading", { name: "Inga flöden än" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Nytt flöde" })).toHaveLength(2);
    cleanup();
    renderPage([], ["flows_view"]);
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
  });

  it("creates a flow with a name and description and opens it", async () => {
    api.POST.mockResolvedValue({
      data: makeFlow({ id: "new-flow", name: "Bygglov", steps: [] }),
      response: new Response(null, { status: 201 })
    });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "Nytt flöde" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));
    const name = within(dialog).getByRole("textbox", { name: /Namn/ });
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.change(name, { target: { value: " Bygglov " } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Beskrivning/ }), {
      target: { value: "Granskar ansökningar." }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/new-flow"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/", {
      body: {
        space_id: "space-1",
        name: "Bygglov",
        description: "Granskar ansökningar."
      }
    });
  });

  it("says at the name when the space already has a flow by that name", async () => {
    api.POST.mockResolvedValue({
      error: { code: "flow_name_taken", message: "Taken.", eneo_error_code: 9017 },
      response: new Response(null, { status: 409 })
    });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "Nytt flöde" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Namn/ }), {
      target: { value: "Medborgarbrev" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));

    expect(
      await within(dialog).findByText(
        "Det finns redan ett flöde med det namnet i ytan. Välj ett annat namn."
      )
    ).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("offers deletion only of the flows the core lets the caller delete", () => {
    renderPage([
      sparse({ id: "f1", name: "Medborgarbrev" }),
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    expect(screen.getByRole("button", { name: "Ta bort Medborgarbrev" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ta bort Remissvar" })).toBeNull();
    cleanup();
    renderPage([
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    expect(screen.queryByRole("columnheader", { name: "Åtgärder" })).toBeNull();
  });

  it("says in words why a deletion was refused", async () => {
    api.DELETE.mockResolvedValue({
      error: { code: "insufficient_space_permission", message: "No.", eneo_error_code: 9007 },
      response: new Response(null, { status: 403 })
    });
    renderPage([sparse({ id: "f1", name: "Medborgarbrev" })]);
    fireEvent.click(screen.getByRole("button", { name: "Ta bort Medborgarbrev" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(messages.flows_refusal_no_permission)
    );
  });

  it("warns before deleting a flow whose runs' evidence could then never be downloaded", async () => {
    renderPage([
      sparse({ id: "f1", name: "Medborgarbrev", metadata_json: null }),
      sparse({
        id: "f2",
        name: "Remissvar",
        metadata_json: { evidence_policy: { allow_export: true } }
      })
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Ta bort Medborgarbrev" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort ”Medborgarbrev”?" });
    expect(
      within(dialog).getByText(new RegExp(messages.flow_delete_evidence_export_off))
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Ta bort Remissvar" }));
    const allowed = await screen.findByRole("alertdialog", { name: "Ta bort ”Remissvar”?" });
    expect(within(allowed).getByText(messages.flows_delete_description)).toBeTruthy();
    expect(
      within(allowed).queryByText(new RegExp(messages.flow_delete_evidence_export_off))
    ).toBeNull();
  });
});

describe("FlowsPage on a phone", () => {
  const flows = () => [
    sparse({
      id: "f1",
      name: "Mötesprotokoll",
      description: "Skriver ut mötet och gör ett protokoll.",
      input_type: "audio",
      output_type: "docx",
      published_version: 2
    }),
    sparse({
      id: "f2",
      name: "Svar på ärende",
      description: null,
      input_type: null,
      output_type: "text",
      published_version: null,
      permissions: flowPermissions({ can_delete: true })
    })
  ];

  it("lists the flows as rows that say what they take and give", async () => {
    setViewport("phone");
    const { container } = renderPage(flows());
    expect(screen.queryByRole("table")).toBeNull();
    const list = screen.getByRole("list", { name: "Flöden" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0]!)
        .getByRole("link", { name: /Mötesprotokoll/ })
        .getAttribute("href")
    ).toBe("/spaces/space-1/flows/f1");
    expect(within(rows[0]!).getByText("Skriver ut mötet och gör ett protokoll.")).toBeTruthy();
    expect(within(rows[0]!).getByText("Indata: Ljud · Resultat: Word-dokument")).toBeTruthy();
    // Typed text or a form has no upload to name: only the result is said.
    expect(within(rows[1]!).getByText("Resultat: Text")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers neither creating, importing nor deleting, and says where that is done", () => {
    setViewport("phone");
    renderPage(flows());
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Importera" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Ta bort/ })).toBeNull();
    expect(screen.getByText("Skapa och redigera flöden görs på dator.")).toBeTruthy();
    // The state is for those who manage flows.
    expect(within(screen.getByRole("list", { name: "Flöden" })).getByText("Utkast")).toBeTruthy();
    cleanup();
    renderPage(flows(), ["flows_view"]);
    expect(screen.queryByText("Skapa och redigera flöden görs på dator.")).toBeNull();
    expect(screen.queryByText("Utkast")).toBeNull();
  });

  it("does not offer a first flow to create on an empty list", () => {
    setViewport("phone");
    renderPage([]);
    expect(screen.getByRole("heading", { name: "Inga flöden än" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
  });

  it("lets a long flow name wrap instead of cutting it to one line", () => {
    setViewport("phone");
    const name =
      "Sammanfattning av nämndens långa protokoll med bilagor till samtliga förvaltningar";
    renderPage([sparse({ id: "f9", name })]);
    // Astryx truncates a plain string label to one line; a node label is ours to wrap.
    expect(screen.getByText(name).className).toContain("break-words");
  });

  it("stays rows, with nothing to create, when the phone is held sideways", () => {
    setViewport({ width: 844, height: 390, pointer: "coarse" });
    renderPage(flows());
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("list", { name: "Flöden" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
  });

  it("searches and filters the rows too, and keeps both across a turn to the tablet layout", async () => {
    setViewport("phone");
    const { container } = renderPage(dated());
    const field = search();
    fireEvent.change(field, { target: { value: "r" } });
    fireEvent.click(screen.getByRole("radio", { name: "Utkast" }));
    expect(screen.getByRole("list", { name: "Flöden" })).toBeTruthy();
    expect(shown()).toEqual(["Mötesprotokoll", "Remissvar"]);
    await expectNoAxeViolations(container);

    field.focus();
    setViewport("tablet-portrait");
    await waitFor(() => expect(screen.getByRole("table", { name: "Flöden" })).toBeTruthy());
    expect(search()).toBe(field);
    expect(document.activeElement).toBe(field);
    expect(field).toHaveProperty("value", "r");
    expect(screen.getByRole("radio", { name: "Utkast" }).getAttribute("aria-checked")).toBe("true");
    expect(shown()).toEqual(["Mötesprotokoll", "Remissvar"]);
  });

  it("keeps the table on a tablet", () => {
    setViewport("tablet-portrait");
    renderPage(flows());
    expect(screen.getByRole("table", { name: "Flöden" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nytt flöde" })).toBeTruthy();
  });

  it("keeps create, import and delete available in a narrow mouse-driven desktop window", () => {
    setViewport({ width: 600, height: 900, pointer: "fine" });
    renderPage(flows());
    expect(screen.getByRole("button", { name: "Nytt flöde" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Importera" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Ta bort.*Svar på ärende/ })).toBeTruthy();
    expect(screen.queryByText("Skapa och redigera flöden görs på dator.")).toBeNull();
  });
});
