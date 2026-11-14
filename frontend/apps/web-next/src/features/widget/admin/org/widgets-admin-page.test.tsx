// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { overview, overviewItem, policy, template } from "./fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { router } from "@/test/navigation";
import { WidgetsAdminPage } from "./widgets-admin-page";

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response("{}") });
}

function showPage({
  items = [overviewItem()],
  templates = [template()],
  route = "/admin/widgets",
  queryClient = testQueryClient()
}: {
  items?: ReturnType<typeof overviewItem>[];
  templates?: ReturnType<typeof template>[];
  route?: string;
  queryClient?: ReturnType<typeof testQueryClient>;
} = {}) {
  api.GET.mockImplementation((path: string) => {
    switch (path) {
      case "/api/v1/admin/widgets/":
        return ok(overview(items));
      case "/api/v1/admin/widget-policy/":
        return ok(policy);
      case "/api/v1/widget-templates/":
        return ok({ items: templates, count: templates.length, total_count: templates.length });
      default:
        return Promise.resolve({
          error: { message: "Not found" },
          response: new Response("{}", { status: 404 })
        });
    }
  });
  return renderInApp(<WidgetsAdminPage />, { route, queryClient });
}

afterEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PATCH.mockReset();
  api.DELETE.mockReset();
});

describe("WidgetsAdminPage", () => {
  it("shows the totals and one card per widget, and the tabs carry their counts", async () => {
    const { container } = showPage({
      items: [overviewItem(), overviewItem({ id: "w2", name: "HR-chatt", status: "draft" })]
    });
    await screen.findByRole("heading", { level: 1, name: "Webbwidgetar" });
    // One active widget is counted in the singular.
    expect(await screen.findByText("1 aktiv")).toBeTruthy();
    const list = screen.getByRole("list", {
      name: "Widgetar med placering, status och användning"
    });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getAllByRole("heading", { level: 2 })).toHaveLength(2);
    expect(within(list).getByRole("link", { name: "Kontaktchatt" }).getAttribute("href")).toBe(
      "/spaces/s1/assistants/a1/widget"
    );
    expect(within(list).getAllByText("Kundtjänst · Kontakt · 1 tillåten webbplats")).toHaveLength(
      2
    );
    const tabs = screen.getByRole("tablist", { name: "Webbwidgetar" });
    expect(within(tabs).getByRole("tab", { name: /Widgetar/ }).textContent).toContain("2");
    expect(within(tabs).getByRole("tab", { name: /Widgetmallar/ }).textContent).toContain("1");
    await act(async () => {
      await expectNoAxeViolations(container);
    });
  });

  it("flags an active widget that is not serving as configured", async () => {
    showPage({ items: [overviewItem({ activation_blockers: ["subtitle_empty"] })] });
    expect(await screen.findByText(/Aktiv, men behöver åtgärdas: /)).toBeTruthy();
  });

  it("asks before pausing a live widget, then pauses it and reloads the list", async () => {
    // The editor's cache of the space's widgets, fresh from a recent visit.
    const queryClient = testQueryClient();
    const editorKey = ["spaces", "s1", "widgets"];
    queryClient.setQueryData(editorKey, [{ id: "w1", status: "active", revision: 3 }]);
    showPage({ queryClient });
    api.POST.mockImplementation(() => ok(overviewItem({ status: "paused" })));
    fireEvent.click(await screen.findByRole("button", { name: "Pausa" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Pausa Kontaktchatt?" });
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Pausa" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/widgets/{id}/pause/", {
        params: { path: { id: "w1" } }
      })
    );
    await waitFor(() =>
      expect(
        api.GET.mock.calls.filter(([p]) => p === "/api/v1/admin/widgets/").length
      ).toBeGreaterThan(1)
    );
    // Reopening the editor within its stale time must not reuse the old revision.
    expect(queryClient.getQueryState(editorKey)?.isInvalidated).toBe(true);
  });

  it("only offers activation when nothing blocks it", async () => {
    showPage({
      items: [
        overviewItem({ id: "w1", name: "Klar", status: "draft" }),
        overviewItem({
          id: "w2",
          name: "Blockerad",
          status: "draft",
          activation_blockers: ["no_origins"]
        })
      ]
    });
    const ready = await screen.findByRole("group", { name: "Åtgärder för Klar" });
    expect(within(ready).getByRole("button", { name: "Aktivera" }).hasAttribute("disabled")).toBe(
      false
    );
    const blocked = screen.getByRole("group", { name: "Åtgärder för Blockerad" });
    const button = within(blocked).getByRole("button", { name: "Aktivera" });
    expect(button.getAttribute("aria-disabled") ?? String(button.hasAttribute("disabled"))).toBe(
      "true"
    );
    expect(within(blocked).getByText(/Kan inte aktiveras: /)).toBeTruthy();
  });

  it("names the MCP servers outside Eneo a widget reaches", async () => {
    showPage({ items: [overviewItem({ external_tools: ["Ärendesystemet", "Bokningen"] })] });
    expect(
      await screen.findByText("MCP-servrar utanför Eneo: Ärendesystemet, Bokningen")
    ).toBeTruthy();
  });

  it("a paused widget with unacknowledged tools is resumed from the widget page", async () => {
    showPage({
      items: [
        overviewItem({
          name: "Bygglov",
          status: "paused",
          external_tools: ["Ärendesystemet"],
          external_tools_acknowledged: false
        })
      ]
    });
    const actions = await screen.findByRole("group", { name: "Åtgärder för Bygglov" });
    const resume = within(actions).getByRole("button", { name: "Återuppta" });
    expect(resume.getAttribute("aria-disabled") ?? String(resume.hasAttribute("disabled"))).toBe(
      "true"
    );
    expect(
      within(actions).getByText(
        "Kan inte aktiveras: Aktivera från widgetsidan för att bekräfta dess verktyg på MCP-servrar utanför Eneo."
      )
    ).toBeTruthy();
    fireEvent.click(resume);
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("WidgetsAdminPage policy", () => {
  it("an organisation can refuse widgets whose assistant uses tools outside Eneo", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok({ ...policy, ...init.body })
    );
    showPage({ route: "/admin/widgets?tab=policy" });
    const allow = await screen.findByRole("switch", {
      name: /^Tillåt widgetar med verktyg på MCP-servrar utanför Eneo/
    });
    expect((allow as HTMLInputElement).checked).toBe(true);
    fireEvent.click(allow);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/admin/widget-policy/",
          expect.objectContaining({ body: { allow_external_tools: false } })
        ),
      { timeout: 2000 }
    );
  });

  it("a policy change refreshes the overview, whose blockers fold the policy in", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok({ ...policy, ...init.body })
    );
    const { queryClient } = showPage({ route: "/admin/widgets?tab=policy" });
    // A space's widget list, cached by an editor visited before the change.
    queryClient.setQueryData(["spaces", "s1", "widgets"], { items: [], count: 0, total_count: 0 });
    queryClient.setQueryData(["spaces", "s1"], { id: "s1" });
    fireEvent.click(await screen.findByRole("switch", { name: "Tillåt widgetar utan botskydd" }));
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/admin/widget-policy/",
          expect.objectContaining({ body: { allow_bot_protection_none: true } })
        ),
      { timeout: 2000 }
    );
    await waitFor(() => {
      const refetched =
        api.GET.mock.calls.filter(([p]) => p === "/api/v1/admin/widgets/").length > 1;
      const stale = queryClient.getQueryState(["admin", "widgets", "overview"])?.isInvalidated;
      expect(refetched || stale === true).toBe(true);
    });
    // Editors fold the policy into their widgets' blockers too; the space itself is untouched.
    await waitFor(() =>
      expect(queryClient.getQueryState(["spaces", "s1", "widgets"])?.isInvalidated).toBe(true)
    );
    expect(queryClient.getQueryState(["spaces", "s1"])?.isInvalidated).toBe(false);
  });

  it("the maximum budget may reach the API's ceiling but not pass it", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok({ ...policy, ...init.body })
    );
    const { queryClient } = showPage({ route: "/admin/widgets?tab=policy" });
    const budget = (await screen.findByRole("spinbutton", {
      name: /Högsta dagliga tokenbudget/
    })) as HTMLInputElement;
    // Numbers are committed when the field is left, never per keystroke.
    fireEvent.change(budget, { target: { value: "2000000000" } });
    fireEvent.blur(budget);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/admin/widget-policy/",
          expect.objectContaining({ body: { max_daily_token_budget: 2_000_000_000 } })
        ),
      { timeout: 2000 }
    );
    expect(queryClient.getQueryData(["widget-policy"])).toMatchObject({
      max_daily_token_budget: 2_000_000_000
    });
    // Beyond the ceiling clamps to it, which is what is already saved.
    fireEvent.change(budget, { target: { value: "2000000001" } });
    fireEvent.blur(budget);
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    expect(budget.value.replace(/\D/g, "")).toBe("2000000000");
  });

  it("holds a minimum above the maximum until the pair is valid, then saves both", async () => {
    api.PATCH.mockImplementation((_path: string, init: { body: Record<string, unknown> }) =>
      ok({ ...policy, ...init.body })
    );
    showPage({ route: "/admin/widgets?tab=policy" });
    const min = await screen.findByRole("spinbutton", { name: /Minst dagar/ });
    const max = screen.getByRole("spinbutton", { name: /Högst dagar/ });
    fireEvent.change(min, { target: { value: "400" } });
    fireEvent.blur(min);
    expect(await screen.findByText(/Minsta lagringstid får inte vara längre/)).toBeTruthy();
    expect(api.PATCH).not.toHaveBeenCalled();
    fireEvent.change(max, { target: { value: "500" } });
    fireEvent.blur(max);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/admin/widget-policy/",
          expect.objectContaining({ body: { min_retention_days: 400, max_retention_days: 500 } })
        ),
      { timeout: 2000 }
    );
    // The field is clean again; the announcer keeps the message it read out.
    expect(min.getAttribute("aria-invalid")).not.toBe("true");
    expect(
      within(screen.getByRole("tabpanel")).queryByText(/Minsta lagringstid får inte vara längre/)
    ).toBeNull();
  });
});

describe("WidgetsAdminPage templates", () => {
  it("creates a template and opens its editor", async () => {
    api.POST.mockImplementation(() => ok(template({ id: "t9", name: "Ny mall" })));
    showPage({ route: "/admin/widgets?tab=templates" });
    fireEvent.click(await screen.findByRole("button", { name: "Ny mall" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/widget-templates/", {
        body: { name: "Ny mall" }
      })
    );
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/admin/widgets/templates/t9"));
    // Leaving can be declined (an unsaved edit elsewhere); the button must work again.
    fireEvent.click(screen.getByRole("button", { name: "Ny mall" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  });

  it("sets the default and asks before deleting", async () => {
    api.PATCH.mockImplementation(() => ok(template({ is_default: true })));
    api.DELETE.mockImplementation(() => ok(null));
    const { queryClient } = showPage({ route: "/admin/widgets?tab=templates" });
    const previous = template({ id: "previous", is_default: true });
    queryClient.setQueryData(["widget-templates", previous.id], previous);
    const list = await screen.findByRole("list", { name: "Widgetmallar" });
    expect(within(list).getByRole("link", { name: "Kommunmallen" }).getAttribute("href")).toBe(
      "/admin/widgets/templates/t1"
    );
    fireEvent.click(within(list).getByRole("button", { name: "Ange som standard" }));
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/widget-templates/{id}/", {
        params: { path: { id: "t1" } },
        body: { is_default: true }
      })
    );
    expect(await within(list).findByText("Standard")).toBeTruthy();
    expect(queryClient.getQueryData(["widget-templates", previous.id])).toMatchObject({
      is_default: false
    });

    fireEvent.click(within(list).getByRole("button", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort mallen?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/admin/widget-templates/{id}/", {
        params: { path: { id: "t1" } }
      })
    );
    await waitFor(() => expect(screen.queryByRole("link", { name: "Kommunmallen" })).toBeNull());
    expect(queryClient.getQueryData(["widget-templates", "t1"])).toBeUndefined();
  });
});
