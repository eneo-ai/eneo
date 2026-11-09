// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { openMenuOnRelease, tap } from "@/test/menus";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
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
  window.localStorage.clear();
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
/** The names of the flows shown, in order, on the cards, in the tables or in the phone rows. */
const shown = () =>
  NAMES.flatMap((name) => {
    const link = screen.queryByRole("link", { name: new RegExp(`^${name}`) });
    return link ? [{ name, link }] : [];
  })
    .sort((a, b) =>
      a.link.compareDocumentPosition(b.link) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
    )
    .map(({ name }) => name);
/** The card (or phone row) of the flow named `name`. */
const card = (name: string) => screen.getByRole("link", { name }).closest("li")!;
const chooseList = () => fireEvent.click(screen.getByRole("button", { name: "Lista" }));
const menuOf = (name: string) => screen.getByRole("button", { name: `Fler åtgärder för ${name}` });

/** Opens a flow's menu and chooses Delete; returns the dialog that asks. */
async function chooseDelete(name: string) {
  const menu = await openMenuOnRelease(menuOf(name));
  tap(within(menu).getByRole("menuitem", { name: "Ta bort" }));
  return screen.findByRole("alertdialog", { name: `Ta bort ”${name}”?` });
}

describe("FlowsPage", () => {
  it("shows the flows as cards in a published and a drafts group, each opening its flow", async () => {
    const { container } = renderPage(dated());
    expect(screen.queryByRole("table")).toBeNull();
    const published = screen.getByRole("region", { name: "Publicerad" });
    const drafts = screen.getByRole("region", { name: "Utkast" });
    expect(
      within(published).getByRole("link", { name: "Medborgarbrev" }).getAttribute("href")
    ).toBe("/spaces/space-1/flows/letter");
    expect(within(drafts).getByRole("link", { name: "Mötesprotokoll" })).toBeTruthy();
    expect(within(drafts).getByRole("link", { name: "Remissvar" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("leaves a group out while it has no flows", () => {
    renderPage([dated()[1]!]);
    expect(screen.queryByRole("region", { name: "Publicerad" })).toBeNull();
    expect(screen.getByRole("region", { name: "Utkast" })).toBeTruthy();
  });

  it("says on each card what the flow takes in and gives back, its steps, whose it is when not the viewer's, and when it changed", () => {
    renderPage(dated());
    const minutes = card("Mötesprotokoll");
    expect(within(minutes).getByText("Skriver ut mötet.")).toBeTruthy();
    expect(within(minutes).getByText("Indata: Ljud · Resultat: Word-dokument")).toBeTruthy();
    expect(within(minutes).getByText("2 steg")).toBeTruthy();
    // Nobody took it over: it is its creator's.
    expect(within(minutes).getByText("Ägare: anna.lind")).toBeTruthy();
    expect(within(minutes).getByText(/^Ändrad .*2026$/)).toBeTruthy();
    // The viewer's own flow names no owner.
    expect(within(card("Medborgarbrev")).queryByText(/^Ägare:/)).toBeNull();
    expect(within(card("Remissvar")).getByText("Ägare: Okänd")).toBeTruthy();
  });

  it("puts the last changed flow first, and sorts by name when asked", async () => {
    renderPage(dated(), ["flows_view"]);
    expect(shown()).toEqual(["Mötesprotokoll", "Remissvar", "Medborgarbrev"]);
    const sort = screen.getByRole("button", { name: /^Sortera: Senast ändrad · Fallande/ });
    const menu = await openMenuOnRelease(sort);
    tap(within(menu).getByRole("menuitemradio", { name: /^Namn · Stigande/ }));
    await waitFor(() => expect(shown()).toEqual(["Medborgarbrev", "Mötesprotokoll", "Remissvar"]));
  });

  it("shows neither groups nor states to those who only run flows, and offers no sort by state", async () => {
    renderPage(dated(), ["flows_view"]);
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByText("Utkast")).toBeNull();
    const menu = await openMenuOnRelease(screen.getByRole("button", { name: /^Sortera/ }));
    expect(within(menu).queryByRole("menuitemradio", { name: /^Status/ })).toBeNull();
  });

  it("orders the groups by state when sorted by it", async () => {
    renderPage(dated());
    const headings = () =>
      screen.getAllByRole("region").map((region) => region.getAttribute("aria-labelledby"));
    const before = headings();
    const menu = await openMenuOnRelease(screen.getByRole("button", { name: /^Sortera/ }));
    tap(within(menu).getByRole("menuitemradio", { name: /^Status · Fallande/ }));
    await waitFor(() => expect(headings()).toEqual([...before].reverse()));
  });

  it("shows a table per group in the list view, with state, steps, owner and last change, and remembers the choice", async () => {
    const { container } = renderPage(dated());
    chooseList();
    expect(screen.getByRole("button", { name: "Lista" }).getAttribute("aria-pressed")).toBe("true");
    const published = screen.getByRole("table", { name: "Flöden · Publicerad" });
    const drafts = screen.getByRole("table", { name: "Flöden · Utkast" });
    expect(within(published).getByText("Publicerad, version 2")).toBeTruthy();
    expect(within(drafts).getAllByText("Utkast")).toHaveLength(2);
    const row = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
    expect(within(row("Mötesprotokoll")).getByText("anna.lind")).toBeTruthy();
    expect(within(row("Mötesprotokoll")).getByText("2 steg")).toBeTruthy();
    expect(within(row("Medborgarbrev")).getByText("Du")).toBeTruthy();
    expect(within(row("Remissvar")).getByText("Okänd")).toBeTruthy();
    await expectNoAxeViolations(container);
    expect(window.localStorage.getItem("eneo:resource-view:flows")).toBe("list");
    cleanup();

    renderPage(dated());
    expect(screen.getByRole("table", { name: "Flöden · Utkast" })).toBeTruthy();
  });

  it("says under each name in the table what the flow takes in and gives back", () => {
    renderPage(dated());
    chooseList();
    const cell = screen.getByRole("link", { name: "Mötesprotokoll" }).parentElement!;
    expect(within(cell).getByText("Skriver ut mötet.")).toBeTruthy();
    expect(within(cell).getByText("Indata: Ljud · Resultat: Word-dokument")).toBeTruthy();
    // A flow with nothing to say about its input or result adds no empty line.
    const bare = screen.getByRole("link", { name: "Remissvar" }).parentElement!;
    expect(bare.children).toHaveLength(1);
  });

  it("pins the table's name column on the page's colour", () => {
    renderPage(dated());
    chooseList();
    const table = screen.getByRole("table", { name: "Flöden · Utkast" });
    expect(
      table.closest('[class*="[--table-sticky-background:var(--color-ax-surface)]"]')
    ).not.toBeNull();
  });

  it.each([
    ["an upright iPad", "tablet-portrait"],
    ["a narrow window", { width: 768, height: 1024, pointer: "fine" }]
  ] as const)("moves the steps and owner under the name in the table on %s", (_, size) => {
    setViewport(size);
    renderPage(dated());
    chooseList();
    const table = screen.getByRole("table", { name: "Flöden · Utkast" });
    expect(within(table).queryByRole("columnheader", { name: "Steg" })).toBeNull();
    expect(within(table).queryByRole("columnheader", { name: "Ägare" })).toBeNull();
    const cell = within(table).getByRole("link", { name: "Mötesprotokoll" }).parentElement!;
    expect(within(cell).getByText("2 steg · Ägare: anna.lind")).toBeTruthy();
    // The viewer's own flow names no owner, as on the cards.
    const own = screen.getByRole("link", { name: "Medborgarbrev" }).parentElement!;
    expect(within(own).getByText(/^\d+ steg$/)).toBeTruthy();
    expect(within(own).queryByText(/Ägare/)).toBeNull();
  });

  it("moves the steps and owner under the name when the page is narrow beside an open sidebar", () => {
    renderPage(dated());
    chooseList();
    const drafts = () => screen.getByRole("table", { name: "Flöden · Utkast" });
    const page = () => drafts().closest("[tabindex='-1']")!;
    const steps = () => within(drafts()).queryByRole("columnheader", { name: "Steg" });
    expect(steps()).toBeTruthy();
    act(() => reportResize(page(), { width: 761 }));
    expect(steps()).toBeNull();
    const cell = screen.getByRole("link", { name: "Mötesprotokoll" }).parentElement!;
    expect(within(cell).getByText("2 steg · Ägare: anna.lind")).toBeTruthy();
    act(() => reportResize(page(), { width: 1101 }));
    expect(steps()).toBeTruthy();
  });

  it("finds a flow by its name, description or what it takes in, and keeps the search in the address", async () => {
    renderPage(dated());
    fireEvent.change(search(), { target: { value: "LJUD" } });
    expect(shown()).toEqual(["Mötesprotokoll"]);
    fireEvent.change(search(), { target: { value: "besvarar" } });
    expect(shown()).toEqual(["Medborgarbrev"]);
    await waitFor(() => expect(replaceUrl).toHaveBeenLastCalledWith(`${LIST}?q=besvarar`));
  });

  it("opens with the search the address holds", () => {
    renderPage(dated(), undefined, `${LIST}?q=protokoll`);
    expect(search()).toHaveProperty("value", "protokoll");
    expect(shown()).toEqual(["Mötesprotokoll"]);
  });

  it("says when no flow matches, then clears the search", async () => {
    const { container } = renderPage(dated(), undefined, `${LIST}?q=finns-inte`);
    expect(screen.getByRole("heading", { name: "Inga flöden matchar din sökning" })).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Rensa sökningen" }));
    expect(document.activeElement).toBe(search());
    expect(search()).toHaveProperty("value", "");
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

  it("offers creating and importing to a role with the old flows grant, which includes managing", () => {
    renderPage([sparse({ id: "f1", name: "Medborgarbrev" })], ["flows"]);
    expect(screen.getByRole("group", { name: "Flöden, åtgärder" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nytt flöde" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Importera" })).toBeTruthy();
  });

  it("asks for the name first and gives focus back to Nytt flöde on Avbryt", async () => {
    renderPage([]);
    const trigger = screen.getAllByRole("button", { name: "Nytt flöde" })[0]!;
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });
    await waitFor(() =>
      expect(document.activeElement).toBe(within(dialog).getByRole("textbox", { name: /Namn/ }))
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("creates a flow with a name and description and opens it", async () => {
    api.POST.mockResolvedValue({
      data: makeFlow({ id: "new-flow", name: "Bygglov", steps: [] }),
      response: new Response(null, { status: 201 })
    });
    renderPage([]);
    fireEvent.click(screen.getAllByRole("button", { name: "Nytt flöde" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Nytt flöde" });
    const name = within(dialog).getByRole("textbox", { name: /Namn/ });

    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa flöde" }));
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

  it("offers deletion only of the flows the core lets the caller delete", async () => {
    renderPage([
      sparse({ id: "f1", name: "Medborgarbrev" }),
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    expect(menuOf("Medborgarbrev")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Fler åtgärder för Remissvar" })).toBeNull();
    cleanup();
    renderPage([
      sparse({ id: "f2", name: "Remissvar", permissions: flowPermissions({ can_delete: false }) })
    ]);
    chooseList();
    expect(screen.queryByRole("columnheader", { name: "Åtgärder" })).toBeNull();
  });

  it("deletes a flow from its menu, says so and refreshes the list", async () => {
    api.DELETE.mockResolvedValue({ data: null, response: new Response(null, { status: 204 }) });
    api.GET.mockResolvedValue({ data: [], response: new Response(null, { status: 200 }) });
    renderPage([sparse({ id: "f1", name: "Medborgarbrev" })]);
    const dialog = await chooseDelete("Medborgarbrev");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("”Medborgarbrev” togs bort"));
    expect(api.DELETE).toHaveBeenCalledWith("/api/v1/flows/{id}/", {
      params: { path: { id: "f1" } }
    });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("says in words why a deletion was refused, with the trace id to quote to support", async () => {
    api.DELETE.mockResolvedValue({
      error: { code: "insufficient_space_permission", message: "No.", eneo_error_code: 9007 },
      response: new Response(null, { status: 403, headers: { "x-trace-id": "trace-1" } })
    });
    renderPage([sparse({ id: "f1", name: "Medborgarbrev" })]);
    const dialog = await chooseDelete("Medborgarbrev");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(messages.flows_refusal_no_permission, {
        description: `${messages.trace_id}: trace-1`
      })
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

    const dialog = await chooseDelete("Medborgarbrev");
    expect(
      within(dialog).getByText(new RegExp(messages.flow_delete_evidence_export_off))
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

    const allowed = await chooseDelete("Remissvar");
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
  /** Seven flows: enough for a phone to show the search. */
  const many = () =>
    Array.from({ length: 7 }, (_, index) =>
      sparse({ id: `f${index}`, name: `Flöde ${index + 1}`, description: null })
    );

  it("lists the flows as rows that say what they take and give", async () => {
    setViewport("phone");
    const { container } = renderPage(flows(), ["flows_view"]);
    expect(screen.queryByRole("table")).toBeNull();
    const row = (name: string) => screen.getByRole("link", { name: new RegExp(name) });
    expect(row("Mötesprotokoll").getAttribute("href")).toBe("/spaces/space-1/flows/f1");
    const first = row("Mötesprotokoll").closest("li")!;
    expect(within(first).getByText("Skriver ut mötet och gör ett protokoll.")).toBeTruthy();
    expect(
      within(first).getByText(/^Indata: Ljud · Resultat: Word-dokument · 2 steg/)
    ).toBeTruthy();
    // Typed text or a form has no upload to name: only the result is said.
    expect(
      within(row("Svar på ärende").closest("li")!).getByText(/^Resultat: Text · /)
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers neither creating, importing nor deleting, and says where that is done", () => {
    setViewport("phone");
    renderPage(flows());
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Importera" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Fler åtgärder/ })).toBeNull();
    expect(screen.getByText("Skapa och redigera flöden görs på dator.")).toBeTruthy();
    // The groups are for those who manage flows.
    expect(screen.getByRole("region", { name: "Utkast" })).toBeTruthy();
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

  it("stays rows, with nothing to create, when the phone is held sideways", () => {
    setViewport("phone-landscape");
    renderPage(flows());
    expect(screen.queryByRole("table")).toBeNull();
    // Rows in a list, not cards in a grid.
    const list = screen.getByRole("link", { name: /Mötesprotokoll/ }).closest("ul")!;
    expect(list.className).not.toContain("grid");
    expect(screen.queryByRole("button", { name: "Nytt flöde" })).toBeNull();
  });

  it("leaves the search out while there are few flows, and offers it with many", () => {
    setViewport("phone");
    renderPage(flows());
    expect(screen.queryByLabelText("Sök flöden")).toBeNull();
    cleanup();
    renderPage(many());
    expect(search()).toBeTruthy();
  });

  it("keeps a search being typed across a turn to the tablet layout", async () => {
    setViewport("phone");
    renderPage(many());
    const field = search();
    fireEvent.change(field, { target: { value: "Flöde 3" } });
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      expect.stringContaining("Flöde 3")
    ]);

    field.focus();
    act(() => setViewport("tablet-portrait"));
    expect(search()).toBe(field);
    expect(document.activeElement).toBe(field);
    expect(field).toHaveProperty("value", "Flöde 3");
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Flöde 3" }).getAttribute("href")).toBe(
        "/spaces/space-1/flows/f2"
      )
    );
  });

  it("shows cards and offers creating on a tablet", () => {
    setViewport("tablet-portrait");
    renderPage(flows());
    expect(screen.getByRole("link", { name: "Mötesprotokoll" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nytt flöde" })).toBeTruthy();
    expect(screen.queryByText("Skapa och redigera flöden görs på dator.")).toBeNull();
  });

  it("keeps create, import and delete available in a narrow mouse-driven desktop window", () => {
    setViewport({ width: 600, height: 900, pointer: "fine" });
    renderPage(flows());
    expect(screen.getByRole("button", { name: "Nytt flöde" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Importera" })).toBeTruthy();
    expect(menuOf("Svar på ärende")).toBeTruthy();
    expect(screen.queryByText("Skapa och redigera flöden görs på dator.")).toBeNull();
  });
});
