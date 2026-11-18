// @vitest-environment jsdom
import type { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Widget, WidgetTemplate } from "./autosave";
import { template } from "./org/fixtures";

const state = vi.hoisted(() => ({ space: null as unknown as Space, routeId: "space-1" }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space, state.routeId) };
});
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { WidgetAdminPage } from "./widget-admin-page";

const ASSISTANT = "a1";
const SPACE_ID = "s1";

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response("{}") });
}

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
    space_id: SPACE_ID,
    target_type: "assistant",
    target_id: ASSISTANT,
    status: "draft",
    token_generation: 0,
    revision: 3,
    name: "Kaffe",
    texts: {
      title: "Kaffehjälpen",
      subtitle: "Du chattar med en AI-assistent.",
      welcome: "Hej!",
      placeholder: "",
      suggested_questions: [],
      footer_text: "",
      footer_link_url: null,
      footer_link_label: null
    },
    theme: { primary_color: "#1F4E79", radius: 12, color_scheme: "auto", position: "bottom-right" },
    persona: { name: "", avatar_icon_id: null, avatar_in_launcher: false },
    limits: {
      daily_token_budget: 500000,
      messages_per_ip_hour: 60,
      max_question_chars: 1000,
      max_session_turns: 20
    },
    privacy: { retention_days: 30, store_feedback_text: false },
    language: "auto",
    allowed_origins: ["https://www.kommun.se"],
    bot_protection: "altcha",
    show_sources: true,
    show_tool_activity: true,
    activation_blockers: [],
    template: null,
    updated_at: "2026-10-28T08:00:00Z",
    created_at: "2026-10-28T08:00:00Z",
    ...overrides
  } as unknown as Widget;
}

function assistant() {
  return {
    id: ASSISTANT,
    name: "Kaffe_tips",
    published: true,
    permissions: ["edit", "publish"],
    icon_id: null,
    mcp_servers: [],
    enabled_capabilities: []
  };
}

function showPage(
  widgets: Widget[],
  permissions: ("widgets" | "admin")[] = ["widgets"],
  {
    templates = [],
    queryClient,
    route
  }: { templates?: WidgetTemplate[]; queryClient?: QueryClient; route?: string } = {}
) {
  state.space = makeSpace({ overrides: { id: SPACE_ID, name: "Test" } });
  api.GET.mockImplementation((path: string) => {
    switch (path) {
      case "/api/v1/assistants/{id}/":
        return ok(assistant());
      case "/api/v1/spaces/{space_id}/widgets/":
        return ok({ items: widgets, count: widgets.length, total_count: widgets.length });
      case "/api/v1/admin/widget-policy/":
        return ok({
          max_daily_token_budget: 1000000,
          min_retention_days: 0,
          max_retention_days: 365,
          allow_bot_protection_none: false
        });
      case "/api/v1/widget-templates/":
        return ok({ items: templates, count: templates.length, total_count: templates.length });
      case "/api/v1/widgets/{id}/usage/":
        return ok({ days: [], budget_used_today: 0, daily_token_budget: 500000 });
      default:
        return Promise.resolve({
          error: { message: "Not found" },
          response: new Response("{}", { status: 404 })
        });
    }
  });
  api.POST.mockImplementation((path: string) => {
    if (path === "/api/v1/widgets/{id}/preview-token/") {
      return ok({ token: "preview-token", expires_in: 900 });
    }
    return ok(widget());
  });
  return renderInApp(
    <WidgetAdminPage
      assistantId={ASSISTANT}
      release={{ version: "1.0.11", channel: "v1", integrity: "sha384-x" }}
      appOrigin="https://eneo.test"
    />,
    { appContext: testAppContext({ permissions }), queryClient, route }
  );
}

const WIDGET_PATH = "/api/v1/widgets/{id}/";
const WIDGETS_PATH = "/api/v1/spaces/{space_id}/widgets/";
const LINK_PATH = "/api/v1/widgets/{id}/link-template/";

/** A 422 as openapi-fetch hands it over: the body on `error`, the status on `response`. */
function refused(detail: unknown) {
  return Promise.resolve({
    error: { detail },
    response: new Response("{}", { status: 422 })
  });
}

/** The published template applied to the widget: its persona copied, persona locked. */
function linked(overrides: Partial<Widget> = {}): Widget {
  return widget({
    revision: 5,
    persona: { name: "Mallen", avatar_icon_id: null, avatar_in_launcher: false },
    template: { id: "t1", name: "Kommunmallen", locked_groups: ["persona"] },
    ...overrides
  });
}

/** Picks the first published template on the appearance tab and confirms linking it. */
async function applyTemplate() {
  fireEvent.click(screen.getByRole("tab", { name: /Utseende/ }));
  fireEvent.click(await screen.findByRole("radio", { name: /Kommunmallen/ }));
  fireEvent.click(screen.getByRole("button", { name: "Koppla till mall" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Koppla till mallen?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Koppla till mall" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
}

afterEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PATCH.mockReset();
});

describe("WidgetAdminPage", () => {
  it("shows the widget's status, its tabs and the real embed page as the preview", async () => {
    const { container } = showPage([widget()]);
    await screen.findByRole("heading", { level: 1, name: "Webbwidget" });
    expect(screen.getByText("Utkast")).toBeTruthy();
    const tabs = screen.getByRole("tablist", { name: "Webbwidget" });
    expect(within(tabs).getAllByRole("tab")).toHaveLength(4);
    for (const name of ["Innehåll", "Utseende", "Regler", "Publicera"]) {
      expect(within(tabs).getByRole("tab", { name: new RegExp(name) })).toBeTruthy();
    }
    // The preview frames the embed page with a preview token in the fragment.
    const frame = (await screen.findByTitle(
      "Förhandsgranskning av chattwidgeten"
    )) as HTMLIFrameElement;
    expect(frame.src).toContain("/embed/wgt_aaaaaaaaaaaaaaaaaaaaaa?preview=1");
    expect(frame.src).toContain("#preview=preview-token");
    await act(async () => {
      await expectNoAxeViolations(container);
    });
  });

  it("marks the selected preview scheme and sends that scheme to the real embed page", async () => {
    showPage([widget()]);
    const frame = (await screen.findByTitle(
      "Förhandsgranskning av chattwidgeten"
    )) as HTMLIFrameElement;
    const schemes = within(
      screen.getByRole("group", { name: "Färgschema i förhandsgranskningen" })
    );
    const automatic = schemes.getByRole("button", { name: "Automatiskt", pressed: true });
    const dark = schemes.getByRole("button", { name: "Mörkt", pressed: false });
    expect(automatic.querySelector("svg.lucide-check")).toBeTruthy();
    expect(dark.querySelector("svg.lucide-check")).toBeNull();
    fireEvent.click(dark);
    expect(dark.getAttribute("aria-pressed")).toBe("true");
    expect(dark.querySelector("svg.lucide-check")).toBeTruthy();
    expect(automatic.querySelector("svg.lucide-check")).toBeNull();
    // A changed address gets a fresh frame rather than a navigation of the old
    // one, so the first frame is gone and the new one carries the scheme.
    expect(frame.isConnected).toBe(false);
    const reloaded = (await screen.findByTitle(
      "Förhandsgranskning av chattwidgeten"
    )) as HTMLIFrameElement;
    expect(new URL(reloaded.src).searchParams.get("scheme")).toBe("dark");
  });

  it("saves an edited name with the widget's revision after a pause", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    // The organisation's overview, fresh from a recent visit: its blockers follow the widget.
    const queryClient = testQueryClient();
    const overviewKey = ["admin", "widgets", "overview"];
    queryClient.setQueryData(overviewKey, { totals: {}, items: [] });
    showPage([widget()], ["widgets"], { queryClient });
    // The widget's own name comes first; the persona's name field is below it.
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Kaffe och te" } });
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/widgets/{id}/",
          expect.objectContaining({ body: { name: "Kaffe och te", revision: 3 } })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(true);
  });

  it("offers activation to tenant admins only and says why to the others", async () => {
    showPage([widget()]);
    const activate = await screen.findByRole("button", { name: "Aktivera" });
    expect(
      activate.getAttribute("aria-disabled") ?? String(activate.hasAttribute("disabled"))
    ).toBe("true");
    expect(screen.getAllByText(/organisationsadministratör/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Arkivera" })).toBeNull();
  });

  it("lets an admin activate and shows the widget as live", async () => {
    showPage([widget()], ["widgets", "admin"]);
    // After showPage, whose default POST answers every call with the draft.
    api.POST.mockImplementation((path: string) =>
      path === "/api/v1/widgets/{id}/activate/"
        ? ok(widget({ status: "active", revision: 4 }))
        : ok({ token: "preview-token", expires_in: 900 })
    );
    const activate = await screen.findByRole("button", { name: "Aktivera" });
    fireEvent.click(activate);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/activate/", expect.anything())
    );
    await screen.findByText("Aktiv");
  });

  it("creates the widget from the assistant's name when there is none", async () => {
    api.POST.mockImplementation((path: string, init: { body: Record<string, unknown> }) =>
      path === "/api/v1/spaces/{space_id}/widgets/"
        ? ok(widget({ name: String(init.body.name) }))
        : ok({ token: "preview-token", expires_in: 900 })
    );
    showPage([]);
    const name = await screen.findByRole("textbox", { name: /^Namn/ });
    expect((name as HTMLInputElement).value).toBe("Kaffe_tips");
    fireEvent.click(screen.getByRole("button", { name: "Skapa widget" }));
    await screen.findByRole("tablist", { name: "Webbwidget" });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/spaces/{space_id}/widgets/",
      expect.objectContaining({
        body: { target_id: ASSISTANT, name: "Kaffe_tips", language: "auto", template_id: null }
      })
    );
  });

  it("stays usable while two suggested questions repeat, and settles once one is changed", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([
      widget({ texts: { ...widget().texts, suggested_questions: ["Öppettider?", "Öppettider?"] } })
    ]);
    const [, second] = await screen.findAllByRole("textbox", { name: /^Föreslagen fråga/ });
    expect(second!.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Frågan finns redan i listan.", { selector: "li *" })).toBeTruthy();
    // The repeated question is held back, which the header counts as unsaved.
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();

    fireEvent.change(second!, { target: { value: "Kontakt?" } });
    fireEvent.blur(second!);
    await waitFor(() => expect(second!.getAttribute("aria-invalid")).toBeNull());
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              texts: expect.objectContaining({ suggested_questions: ["Öppettider?", "Kontakt?"] })
            })
          })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("Maximum update depth");
  });

  it("saves the remaining question when removing a duplicate", async () => {
    const saved = widget();
    saved.texts.suggested_questions = ["A", "B"];
    api.PATCH.mockImplementation((_path: string, { body }: { body: Partial<Widget> }) =>
      ok({ ...saved, ...body })
    );
    showPage([saved]);
    const second = await screen.findByRole("textbox", { name: "Föreslagen fråga 2" });
    fireEvent.change(second, { target: { value: "A" } });
    expect(await screen.findByText("Frågan finns redan i listan.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ta bort fråga 1" }));
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              texts: expect.objectContaining({ suggested_questions: ["A"] })
            })
          })
        ),
      { timeout: 2000 }
    );
  });

  it("discards an invalid origin on conflict reload even when the saved origins are unchanged", async () => {
    const saved = widget();
    api.PATCH.mockResolvedValue({
      error: { detail: { code: "widget_revision_conflict" } },
      response: new Response("{}", { status: 409 })
    });
    showPage([saved]);
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Andra namnet" } });
    fireEvent.click(screen.getByRole("tab", { name: /Regler/ }));
    const origin = await screen.findByRole("textbox", { name: /Tillåtna webbplatser/ });
    fireEvent.change(origin, { target: { value: "invalid" } });
    const reload = await screen.findByRole(
      "button",
      { name: /Ladda om och kasta/ },
      { timeout: 2000 }
    );
    api.GET.mockImplementationOnce(() => ok({ ...saved, revision: 4 }));
    fireEvent.click(reload);
    await waitFor(() =>
      expect(
        (screen.getByRole("textbox", { name: /Tillåtna webbplatser/ }) as HTMLTextAreaElement).value
      ).toBe("https://www.kommun.se")
    );
  });

  it("an edit made while the widget pauses is saved with the revision the pause returned", async () => {
    let finishPause!: (paused: Widget) => void;
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, status: "paused", revision: 8 }))
    );
    showPage([widget({ status: "active", activated_at: "2026-09-01T00:00:00Z" })]);
    // After showPage, whose default POST answers every call with the draft.
    api.POST.mockImplementation((path: string) =>
      path === "/api/v1/widgets/{id}/pause/"
        ? new Promise<{ data: Widget; response: Response }>((resolve) => {
            finishPause = (data) => resolve({ data, response: new Response("{}") });
          })
        : ok({ token: "preview-token", expires_in: 900 })
    );
    fireEvent.click(await screen.findByRole("button", { name: "Pausa" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/pause/", expect.anything())
    );

    // Typed while the pause is still in flight: it waits for the new revision.
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Kaffe och te" } });
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(api.PATCH).not.toHaveBeenCalled();

    await act(async () => finishPause(widget({ status: "paused", revision: 7 })));
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({ body: { name: "Kaffe och te", revision: 7 } })
        ),
      { timeout: 2000 }
    );
  });

  it("a save finished after leaving the page still reaches the list", async () => {
    const queryClient = testQueryClient();
    let finishSave!: (saved: Widget) => void;
    api.PATCH.mockImplementation(
      () =>
        new Promise<{ data: Widget; response: Response }>((resolve) => {
          finishSave = (data) => resolve({ data, response: new Response("{}") });
        })
    );
    const view = showPage([widget()], ["widgets"], { queryClient });
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Kaffe och te" } });
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1), { timeout: 2000 });
    // Left during the save (a confirmed navigation); the answer lands afterwards.
    view.unmount();
    await act(async () => finishSave(widget({ name: "Kaffe och te", revision: 4 })));
    await waitFor(() =>
      expect(
        (queryClient.getQueryData(["spaces", "s1", "widgets"]) as Widget[]).find(
          (item) => item.id === "w1"
        )
      ).toMatchObject({ name: "Kaffe och te", revision: 4 })
    );
  });

  it("a pause finished after leaving the page still reaches the list", async () => {
    const queryClient = testQueryClient();
    let finishPause!: (paused: Widget) => void;
    const view = showPage(
      [widget({ status: "active", activated_at: "2026-09-01T00:00:00Z" })],
      ["widgets"],
      { queryClient }
    );
    api.POST.mockImplementation((path: string) =>
      path === "/api/v1/widgets/{id}/pause/"
        ? new Promise<{ data: Widget; response: Response }>((resolve) => {
            finishPause = (data) => resolve({ data, response: new Response("{}") });
          })
        : ok({ token: "preview-token", expires_in: 900 })
    );
    fireEvent.click(await screen.findByRole("button", { name: "Pausa" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/pause/", expect.anything())
    );
    view.unmount();
    await act(async () => finishPause(widget({ status: "paused", revision: 7 })));
    await waitFor(() =>
      expect(
        (queryClient.getQueryData(["spaces", "s1", "widgets"]) as Widget[]).find(
          (item) => item.id === "w1"
        )
      ).toMatchObject({ status: "paused", revision: 7 })
    );
  });

  it("a blank name, a held disclosure and a bad persona name all count as unsaved", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget({ status: "active", activated_at: "2026-09-01T00:00:00Z" })]);
    const [name, personaName] = await screen.findAllByRole("textbox", { name: /^Namn/ });

    fireEvent.change(name!, { target: { value: "" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    fireEvent.change(name!, { target: { value: "Kontaktchatt" } });
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });

    // A live widget keeps its disclosure, so a blank one is held, not sent.
    const subtitle = screen.getByRole("textbox", { name: /^Beskrivning/ });
    fireEvent.change(subtitle, { target: { value: "" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    fireEvent.change(subtitle, { target: { value: "AI" } });
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });

    fireEvent.change(personaName!, { target: { value: "1Robo" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    fireEvent.change(personaName!, { target: { value: "Robo" } });
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
  });

  it("a link or a question typed but not yet committed counts as unsaved", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget()]);
    const link = await screen.findByRole("textbox", { name: /^Länk i sidfoten/ });
    fireEvent.change(link, { target: { value: "https://www.kommun.se/personuppgifter" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(api.PATCH).not.toHaveBeenCalled();
    fireEvent.blur(link);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              texts: expect.objectContaining({
                footer_link_url: "https://www.kommun.se/personuppgifter"
              })
            })
          })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });

    fireEvent.click(screen.getByRole("button", { name: "Lägg till fråga" }));
    const question = await screen.findByRole("textbox", { name: /^Föreslagen fråga/ });
    // An empty new row is not an edit yet.
    expect(screen.queryByText("1 osparad ändring")).toBeNull();
    fireEvent.change(question, { target: { value: "Kontakt?" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    fireEvent.blur(question);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              texts: expect.objectContaining({ suggested_questions: ["Kontakt?"] })
            })
          })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
  });

  it("an incomplete colour counts as unsaved until it is corrected", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget()]);
    fireEvent.click(await screen.findByRole("tab", { name: /Utseende/ }));
    const colour = await screen.findByRole("textbox", { name: /^Primärfärg/ });
    fireEvent.change(colour, { target: { value: "#12" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(api.PATCH).not.toHaveBeenCalled();
    // Cleared is held too: the primary colour has no empty value to save.
    fireEvent.change(colour, { target: { value: "" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(colour.getAttribute("aria-invalid")).toBe("true");
    expect(api.PATCH).not.toHaveBeenCalled();

    fireEvent.change(colour, { target: { value: "#123456" } });
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              theme: expect.objectContaining({ primary_color: "#123456" })
            })
          })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
  });

  it("a template that supplies the subtitle releases a blank one held before it", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, status: "active", revision: 4 }))
    );
    const live = { status: "active" as const, activated_at: "2026-09-01T00:00:00Z" };
    showPage([widget(live)], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH
        ? ok(
            linked({
              ...live,
              texts: { ...widget().texts, subtitle: "Från mallen" },
              template: {
                id: "t1",
                name: "Kommunmallen",
                locked_groups: ["persona", "legal_texts"]
              }
            })
          )
        : path === "/api/v1/widgets/{id}/pause/"
          ? ok(widget({ status: "paused", revision: 6 }))
          : ok({ token: "preview-token", expires_in: 900 })
    );
    // A live widget keeps its subtitle, so the blank is held, not sent.
    const subtitle = await screen.findByRole("textbox", { name: /^Beskrivning/ });
    fireEvent.change(subtitle, { target: { value: "" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();

    await applyTemplate();
    await waitFor(() => expect((subtitle as HTMLInputElement).value).toBe("Från mallen"));
    expect(subtitle.getAttribute("aria-invalid")).toBeNull();
    await waitFor(() => expect(screen.queryByText("1 osparad ändring")).toBeNull());

    // Pausing frees the subtitle; the discarded blank must not be sent then.
    fireEvent.click(screen.getByRole("button", { name: "Pausa" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/pause/", expect.anything())
    );
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("a template that repeats the saved subtitle and locks it drops a blank held before it", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, status: "active", revision: 4 }))
    );
    const live = { status: "active" as const, activated_at: "2026-09-01T00:00:00Z" };
    showPage([widget(live)], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH
        ? ok(
            linked({
              ...live,
              template: {
                id: "t1",
                name: "Kommunmallen",
                locked_groups: ["persona", "legal_texts"]
              }
            })
          )
        : path === "/api/v1/widgets/{id}/pause/"
          ? ok(widget({ status: "paused", revision: 6 }))
          : ok({ token: "preview-token", expires_in: 900 })
    );
    const subtitle = await screen.findByRole("textbox", { name: /^Beskrivning/ });
    const saved = (subtitle as HTMLInputElement).value;
    fireEvent.change(subtitle, { target: { value: "" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();

    // The template's subtitle is the one saved before: only the lock changes.
    await applyTemplate();
    await waitFor(() => expect((subtitle as HTMLInputElement).value).toBe(saved));
    expect(subtitle.getAttribute("aria-invalid")).toBeNull();
    await waitFor(() => expect(screen.queryByText("1 osparad ändring")).toBeNull());

    // Pausing frees the subtitle; the discarded blank must not be sent then.
    fireEvent.click(screen.getByRole("button", { name: "Pausa" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/pause/", expect.anything())
    );
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("a template that repeats the saved colour and locks it drops an incomplete one held before it", async () => {
    showPage([widget()], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH
        ? ok(
            linked({ template: { id: "t1", name: "Kommunmallen", locked_groups: ["appearance"] } })
          )
        : ok({ token: "preview-token", expires_in: 900 })
    );
    fireEvent.click(await screen.findByRole("tab", { name: /Utseende/ }));
    const colour = await screen.findByRole("textbox", { name: /^Primärfärg/ });
    const saved = (colour as HTMLInputElement).value;
    fireEvent.change(colour, { target: { value: "#1" } });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(colour.getAttribute("aria-invalid")).toBe("true");

    await applyTemplate();
    await waitFor(() => expect((colour as HTMLInputElement).value).toBe(saved));
    expect(colour.getAttribute("aria-invalid")).not.toBe("true");
    await waitFor(() => expect(screen.queryByText("1 osparad ändring")).toBeNull());
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("a template that repeats the saved link and persona name and locks them drops refused drafts held before it", async () => {
    showPage([widget()], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH
        ? ok(
            linked({
              persona: widget().persona,
              template: {
                id: "t1",
                name: "Kommunmallen",
                locked_groups: ["persona", "legal_texts"]
              }
            })
          )
        : ok({ token: "preview-token", expires_in: 900 })
    );
    const link = await screen.findByRole("textbox", { name: /^Länk i sidfoten/ });
    fireEvent.change(link, { target: { value: "invalid" } });
    fireEvent.blur(link);
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(link.getAttribute("aria-invalid")).toBe("true");
    const [, personaName] = screen.getAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(personaName!, { target: { value: "1Robo" } });
    expect(personaName!.getAttribute("aria-invalid")).toBe("true");

    // The template's link and persona are the ones saved before: only the locks change.
    await applyTemplate();
    await waitFor(() => expect((link as HTMLInputElement).value).toBe(""));
    await waitFor(() => expect((personaName as HTMLInputElement).value).toBe(""));
    expect(link.getAttribute("aria-invalid")).not.toBe("true");
    expect(personaName!.getAttribute("aria-invalid")).not.toBe("true");
    await waitFor(() => expect(screen.queryByText("1 osparad ändring")).toBeNull());
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("a website list typed but not yet committed counts as unsaved", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget()]);
    fireEvent.click(await screen.findByRole("tab", { name: /Regler/ }));
    const origins = await screen.findByRole("textbox", { name: /Tillåtna webbplatser/ });
    fireEvent.change(origins, {
      target: { value: "https://www.kommun.se\nhttps://ny.kommun.se" }
    });
    expect(await screen.findByText("1 osparad ändring")).toBeTruthy();
    expect(api.PATCH).not.toHaveBeenCalled();
    fireEvent.blur(origins);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          WIDGET_PATH,
          expect.objectContaining({
            body: expect.objectContaining({
              allowed_origins: ["https://www.kommun.se", "https://ny.kommun.se"]
            })
          })
        ),
      { timeout: 2000 }
    );
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
  });

  it("linking a template lets its cached follower count go", async () => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(["widget-templates", "t1"], template());
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget()], ["widgets"], { templates: [template()], queryClient });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH ? ok(linked()) : ok({ token: "preview-token", expires_in: 900 })
    );
    await screen.findAllByRole("textbox", { name: /^Namn/ });
    expect(queryClient.getQueryState(["widget-templates", "t1"])?.isInvalidated).toBe(false);
    await applyTemplate();
    await waitFor(() =>
      expect(queryClient.getQueryState(["widget-templates", "t1"])?.isInvalidated).toBe(true)
    );
  });

  it("links a template with the revision the save it waited for returned", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    showPage([widget()], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH ? ok(linked()) : ok({ token: "preview-token", expires_in: 900 })
    );
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    // The name edit is still queued when the template is applied.
    fireEvent.change(name!, { target: { value: "Kaffe och te" } });
    expect(api.PATCH).not.toHaveBeenCalled();
    await applyTemplate();

    expect(api.PATCH).toHaveBeenCalledWith(
      WIDGET_PATH,
      expect.objectContaining({ body: { name: "Kaffe och te", revision: 3 } })
    );
    expect(api.POST).toHaveBeenCalledWith(
      LINK_PATH,
      expect.objectContaining({ body: { template_id: "t1", revision: 4 } })
    );
    expect(await screen.findByText("Följer mallen ”Kommunmallen”")).toBeTruthy();
  });

  it("shows the template's persona after linking and clears only that refusal", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) => {
      const locs = [
        ...("name" in init.body ? [["body", "name"]] : []),
        ...("persona" in init.body ? [["body", "persona", "name"]] : [])
      ];
      return locs.length > 0
        ? refused(locs.map((loc) => ({ loc, msg: "Invalid", type: "value_error" })))
        : ok(widget({ ...init.body, revision: 4 }));
    });
    showPage([widget()], ["widgets"], { templates: [template()] });
    api.POST.mockImplementation((path: string) =>
      path === LINK_PATH ? ok(linked()) : ok({ token: "preview-token", expires_in: 900 })
    );
    const [name, personaName] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Kaffe 2" } });
    fireEvent.change(personaName!, { target: { value: "Kim" } });
    // One save carries both; the server refuses both groups.
    const personaRefused = "Värdet godtogs inte. Ändra det så sparas det igen.";
    expect(await screen.findAllByText("Ange ett namn.", {}, { timeout: 2000 })).not.toHaveLength(0);
    expect(screen.getAllByText(personaRefused)).not.toHaveLength(0);

    await applyTemplate();

    expect(api.POST).toHaveBeenCalledWith(
      LINK_PATH,
      expect.objectContaining({ body: { template_id: "t1", revision: 3 } })
    );
    // The release replaced the persona, so its refused edit is gone with it.
    await waitFor(() => expect((personaName as HTMLInputElement).value).toBe("Mallen"));
    expect(screen.queryAllByText(personaRefused)).toHaveLength(0);
    // The widget's name is not part of a release: still refused, still shown.
    expect((name as HTMLInputElement).value).toBe("Kaffe 2");
    expect(screen.getAllByText("Ange ett namn.")).not.toHaveLength(0);
  });

  it("reopens within the list's stale time on the saved widget and its revision", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok(widget({ ...init.body, revision: 4 }))
    );
    const queryClient = testQueryClient();
    const first = showPage([widget()], ["widgets"], { queryClient });
    const [name] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name!, { target: { value: "Kaffe och te" } });
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1), { timeout: 2000 });
    await screen.findByText("Alla ändringar sparade", { selector: "section *" });
    first.unmount();

    // The list is fresh, so the page is built from the cache, not fetched.
    const listed = api.GET.mock.calls.filter(([path]) => path === WIDGETS_PATH).length;
    showPage([widget()], ["widgets"], { queryClient });
    const [reopened] = await screen.findAllByRole("textbox", { name: /^Namn/ });
    expect((reopened as HTMLInputElement).value).toBe("Kaffe och te");
    expect(api.GET.mock.calls.filter(([path]) => path === WIDGETS_PATH)).toHaveLength(listed);

    fireEvent.change(reopened!, { target: { value: "Kaffe, te och saft" } });
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenLastCalledWith(
          WIDGET_PATH,
          expect.objectContaining({ body: { name: "Kaffe, te och saft", revision: 4 } })
        ),
      { timeout: 2000 }
    );
  });
});
