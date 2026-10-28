// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { router } from "@/test/navigation";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const template = (id: string, name: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name,
  description: "",
  category: "Upphandling",
  completion_model_name: null,
  usage_count: 2,
  is_default: false,
  original_snapshot: null,
  deleted_at: null,
  created_at: "2026-09-01T09:00:00Z",
  icon_name: null,
  ...overrides
});

const ASSISTANTS = [
  template("a1", "Upphandlingsassistent", {
    category: "communication",
    description: "Hjälper till med upphandlingar",
    icon_name: "rocket",
    is_default: true,
    usage_count: 1
  }),
  template("a2", "Avtalsgranskare", { category: "advice", usage_count: 7 })
];
const APPS = [
  template("p1", "Protokollsammanfattare", {
    category: "transcription",
    input_type: "audio-upload"
  }),
  template("p2", "Gammal app", { category: "misc", input_type: "text" })
];
const DELETED = [template("d1", "Gammal mall", { deleted_at: "2026-10-20T09:00:00Z" })];

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    ...api,
    GET: (path: string) => {
      const items =
        path === "/api/v1/admin/templates/assistants/"
          ? ASSISTANTS
          : path === "/api/v1/admin/templates/apps/"
            ? APPS
            : path.endsWith("/deleted")
              ? DELETED
              : [];
      return Promise.resolve({ data: { items }, response: new Response("{}") });
    }
  }
}));

import { TemplatesPage } from "./templates-page";

afterEach(() => {
  cleanup();
  for (const method of Object.values(api)) method.mockReset();
});

const withTemplates = { appContext: testAppContext({ settings: { using_templates: true } }) };

function names(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]!.querySelector(".font-medium")?.textContent);
}

describe("TemplatesPage", () => {
  it("sends the admin to /admin while the organisation does not use templates", () => {
    const { container } = renderInApp(<TemplatesPage />);
    expect(router.replace).toHaveBeenCalledWith("/admin");
    expect(container.textContent).toBe("");
  });

  it("names each tab's table after the tab", async () => {
    const { container } = renderInApp(<TemplatesPage />, withTemplates);

    const assistants = await screen.findByRole("table", { name: "Assistenter" });
    expect(within(assistants).getByText("Upphandlingsassistent")).toBeTruthy();
    // Each row's menu says whose it is.
    expect(
      within(assistants).getByRole("button", { name: "Fler åtgärder för Upphandlingsassistent" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Appar" }));
    const apps = await screen.findByRole("table", { name: "Appar" });
    expect(within(apps).getByText("Protokollsammanfattare")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    expect(within(deleted).getAllByText("Gammal mall")).toHaveLength(2);
  });

  it("shows each template's icon, description, category, usage and featured mark", async () => {
    renderInApp(<TemplatesPage />, withTemplates);
    const table = await screen.findByRole("table", { name: "Assistenter" });
    const row = within(table).getByText("Upphandlingsassistent").closest("tr")!;

    expect(within(row).getByText("Hjälper till med upphandlingar")).toBeTruthy();
    expect(within(row).getByText("Utvald")).toBeTruthy();
    expect(within(row).getByText("Kommunikation")).toBeTruthy();
    expect(within(row).getByText("1 instans")).toBeTruthy();
    await waitFor(() => expect(row.querySelector("svg.lucide-rocket")).toBeTruthy());
  });

  it("names each app template's input type, or shows a stored unknown one as it is", async () => {
    renderInApp(<TemplatesPage />, withTemplates);
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Appar" }));
    const table = await screen.findByRole("table", { name: "Appar" });

    expect(within(table).getByText("Ladda upp ljudfil")).toBeTruthy();
    expect(within(table).getByText("text")).toBeTruthy();
    expect(within(table).getByText("Transkription")).toBeTruthy();
  });

  it("filters by name, category or input type, and sorts from the column headers", async () => {
    renderInApp(<TemplatesPage />, withTemplates);
    const table = await screen.findByRole("table", { name: "Assistenter" });
    expect(names(table)).toEqual(["Upphandlingsassistent", "Avtalsgranskare"]);

    fireEvent.click(within(table).getByRole("button", { name: /Mallnamn/ }));
    await waitFor(() => expect(names(table)).toEqual(["Avtalsgranskare", "Upphandlingsassistent"]));
    fireEvent.click(within(table).getByRole("button", { name: /Användning/ }));
    await waitFor(() => expect(names(table)).toEqual(["Upphandlingsassistent", "Avtalsgranskare"]));

    const filter = screen.getByRole("textbox", { name: "Filtrera Assistenter..." });
    // The category as shown.
    fireEvent.change(filter, { target: { value: "rådgivning" } });
    expect(names(screen.getByRole("table", { name: "Assistenter" }))).toEqual(["Avtalsgranskare"]);

    fireEvent.change(filter, { target: { value: "finns inte" } });
    expect(screen.queryByRole("table", { name: "Assistenter" })).toBeNull();
    expect(screen.getByText("Inga resultat hittades")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Appar" }));
    const appFilter = await screen.findByRole("textbox", { name: "Filtrera Appar..." });
    // The input type as shown.
    fireEvent.change(appFilter, { target: { value: "ljudfil" } });
    expect(names(screen.getByRole("table", { name: "Appar" }))).toEqual(["Protokollsammanfattare"]);
  });

  it("deletes a template for good only once its name is typed", async () => {
    api.DELETE.mockResolvedValue({ data: null, response: new Response(null, { status: 204 }) });
    renderInApp(<TemplatesPage />, withTemplates);
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    fireEvent.click(within(deleted).getAllByRole("button", { name: "Ta bort permanent" })[0]!);

    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort mall permanent" });
    // The warning names what goes.
    expect(within(dialog).getByText("Gammal mall")).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Ta bort permanent" });
    fireEvent.click(confirm);
    const typed = within(dialog).getByLabelText(
      'Skriv "Gammal mall" för att bekräfta permanent borttagning'
    );
    expect(typed.getAttribute("aria-invalid")).toBe("true");
    expect(api.DELETE).not.toHaveBeenCalled();

    fireEvent.change(typed, { target: { value: "Gammal mall" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(api.DELETE).toHaveBeenCalledTimes(1));
    expect(api.DELETE.mock.calls[0]![0]).toBe(
      "/api/v1/admin/templates/assistants/{template_id}/permanent"
    );
  });

  it("keeps focus on a busy Återställ and restores once", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<TemplatesPage />, withTemplates);
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    const restore = within(deleted).getAllByRole("button", { name: "Återställ" })[0]!;
    restore.focus();

    fireEvent.click(restore);

    await waitFor(() => expect(restore.getAttribute("aria-busy")).toBe("true"));
    expect(restore.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(restore);
    fireEvent.click(restore);
    expect(api.POST).toHaveBeenCalledTimes(1);
  });
});
