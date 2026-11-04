// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { WidgetTemplate } from "../autosave";
import { template, texts } from "./fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { WidgetTemplatePage } from "./widget-template-page";

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response("{}") });
}

function showPage(current: WidgetTemplate) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/widget-templates/{id}/"
      ? ok(current)
      : Promise.resolve({
          error: { message: "Not found" },
          response: new Response("{}", { status: 404 })
        })
  );
  api.PATCH.mockImplementation((_path: string, init: { body: Partial<WidgetTemplate> }) =>
    ok({ ...current, ...init.body, has_unpublished_changes: true })
  );
  api.POST.mockImplementation(() =>
    ok({ ...current, has_unpublished_changes: false, published_at: "2026-09-21T12:00:00Z" })
  );
  return renderInApp(<WidgetTemplatePage templateId="t1" />, {
    route: "/admin/widgets/templates/t1"
  });
}

afterEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PATCH.mockReset();
});

describe("WidgetTemplatePage", () => {
  it("reports an in-flight draft save before confirming that all changes are saved", async () => {
    showPage(template());
    await screen.findByRole("heading", { level: 1, name: "Kommunmallen" });
    let finishSave: (saved: WidgetTemplate) => void = () => {};
    api.PATCH.mockReturnValue(
      new Promise<{ data: WidgetTemplate; response: Response }>((resolve) => {
        finishSave = (data) => resolve({ data, response: new Response("{}") });
      })
    );

    fireEvent.click(screen.getByRole("switch", { name: "Upplysning och sidfot" }));
    await screen.findByText("Sparar…", {}, { timeout: 2000 });
    expect(screen.queryByText("Alla ändringar sparade")).toBeNull();
    await act(async () =>
      finishSave(
        template({
          locked_groups: ["appearance", "language", "legal_texts"],
          has_unpublished_changes: true
        })
      )
    );
    expect(await screen.findByText("Alla ändringar sparade")).toBeTruthy();
  });

  it("keeps a failed draft save visible in the header instead of claiming the changes were saved", async () => {
    showPage(template());
    await screen.findByRole("heading", { level: 1, name: "Kommunmallen" });
    let refuseSave: () => void = () => {};
    api.PATCH.mockReturnValue(
      new Promise<never>((_resolve, reject) => {
        refuseSave = () => reject(new Error("The connection was lost"));
      })
    );

    fireEvent.click(screen.getByRole("switch", { name: "Upplysning och sidfot" }));
    await screen.findByText("Sparar…", {}, { timeout: 2000 });
    await act(async () => refuseSave());
    expect(await screen.findByRole("link", { name: "Kunde inte spara ändringarna" })).toBeTruthy();
    expect(screen.queryByText("Alla ändringar sparade")).toBeNull();
  });

  it("a lock toggle only edits the draft and marks it unpublished", async () => {
    const { container, queryClient } = showPage(template());
    await screen.findByRole("heading", { level: 1, name: "Kommunmallen" });
    expect(screen.getByText(/^Publicerad /)).toBeTruthy();
    const lock = screen.getByRole("switch", { name: "Upplysning och sidfot" });
    fireEvent.click(lock);
    await waitFor(
      () =>
        expect(api.PATCH).toHaveBeenCalledWith(
          "/api/v1/admin/widget-templates/{id}/",
          expect.objectContaining({
            body: { locked_groups: ["appearance", "language", "legal_texts"] }
          })
        ),
      { timeout: 2000 }
    );
    expect(await screen.findByText("Opublicerade ändringar")).toBeTruthy();
    expect(queryClient.getQueryData(["widget-templates", "t1"])).toMatchObject({
      has_unpublished_changes: true,
      locked_groups: ["appearance", "language", "legal_texts"]
    });
    expect(api.POST).not.toHaveBeenCalled();
    await act(async () => {
      await expectNoAxeViolations(container);
    });
  });

  it("publishing to followers asks first, says what changes, then shows the release as current", async () => {
    const { queryClient } = showPage(
      template({
        has_unpublished_changes: true,
        theme: { primary_color: "#654321", radius: 12 },
        texts: { ...texts, title: "Fråga kommunen" },
        locked_groups: ["appearance"]
      })
    );
    const followers = ["spaces", "s1", "widgets"];
    queryClient.setQueryData(followers, []);
    fireEvent.click(await screen.findByRole("button", { name: "Publicera" }));
    const dialog = await screen.findByRole("dialog", { name: "Publicera till 3 widgetar?" });
    expect(api.POST).not.toHaveBeenCalled();
    const changes = within(dialog).getByRole("list", { name: "Vad publiceringen ändrar" });
    expect(within(changes).getByText(/^Ersätts på widgetarna direkt: Utseende/)).toBeTruthy();
    expect(within(changes).getByText(/^Släppta lås.*Språk/)).toBeTruthy();
    expect(within(changes).getByText(/^Ändrade men inte låsta.*Ordval/)).toBeTruthy();
    expect(within(changes).queryByText(/följer mallen ändras inte/)).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Publicera" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/widget-templates/{id}/publish/", {
        params: { path: { id: "t1" } }
      })
    );
    expect(await screen.findByText(/^Publicerad /)).toBeTruthy();
    expect(queryClient.getQueryState(followers)?.isInvalidated).toBe(true);
  });

  it("the publish dialog says when the followers do not change at all", async () => {
    showPage(template({ has_unpublished_changes: true, description: "Ny beskrivning" }));
    fireEvent.click(await screen.findByRole("button", { name: "Publicera" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/följer mallen ändras inte/)).toBeTruthy();
    expect(within(dialog).queryByText(/^Ersätts på widgetarna/)).toBeNull();
  });

  it("a template nobody follows publishes without a question", async () => {
    showPage(
      template({
        linked_widgets: 0,
        published_at: null,
        published: null,
        has_unpublished_changes: true
      })
    );
    expect(await screen.findByText("Inte publicerad")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Publicera" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a blank name is flagged and never sent", async () => {
    showPage(template());
    // The template's own name comes first; the persona's name field is below it.
    const [name] = (await screen.findAllByRole("textbox", { name: /^Namn/ })) as HTMLInputElement[];
    fireEvent.change(name!, { target: { value: "   " } });
    expect(await screen.findByText("Ange ett namn.")).toBeTruthy();
    expect(name!.getAttribute("aria-invalid")).toBe("true");
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("the legal-texts lock waits for a subtitle", async () => {
    showPage(template({ texts: { ...texts, subtitle: "" } }));
    const lock = await screen.findByRole("switch", { name: "Upplysning och sidfot" });
    expect(lock.hasAttribute("disabled") || lock.getAttribute("aria-disabled") === "true").toBe(
      true
    );
    expect(screen.getAllByText(/Lägg först till en underrubrik/).length).toBeGreaterThan(0);
  });
});
