// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { AUDIT_ACTION_CONFIG_KEY, type ActionConfig, type CategoryConfig } from "./audit";
import { AuditConfig } from "./audit-config";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const ok = (data: unknown) => Promise.resolve({ data, response: new Response() });
const failure = () => new EneoApiError("test failure", { status: 503, code: 9024 });
let categories: CategoryConfig[];
let actions: ActionConfig[];
let failCategory: boolean;
let failActions: boolean;
let failRefresh: boolean;
let normalize: boolean;

beforeEach(() => {
  categories = [
    {
      category: "admin_actions",
      enabled: true,
      action_count: 2,
      example_actions: ["user_created", "user_deleted"]
    }
  ];
  actions = [
    { action: "user_created", category: "admin_actions", enabled: true },
    { action: "user_deleted", category: "admin_actions", enabled: true }
  ];
  failCategory = failActions = failRefresh = normalize = false;
  api.GET.mockImplementation((path: string) => {
    if (failRefresh) return Promise.reject(failure());
    return ok(structuredClone(path.endsWith("/actions") ? { actions } : { categories }));
  });
  api.PATCH.mockImplementation(
    (
      path: string,
      { body }: { body: { updates: { category?: string; action?: string; enabled: boolean }[] } }
    ) => {
      if (path.endsWith("/actions")) {
        if (failActions) return Promise.reject(failure());
        actions = actions.map((item) => ({
          ...item,
          enabled: normalize
            ? true
            : (body.updates.find((update) => update.action === item.action)?.enabled ??
              item.enabled)
        }));
        return ok({ actions: structuredClone(actions) });
      }
      if (failCategory) return Promise.reject(failure());
      categories = categories.map((item) => ({
        ...item,
        enabled:
          body.updates.find((update) => update.category === item.category)?.enabled ?? item.enabled
      }));
      // user_created inherits the category, user_deleted has an explicit enabled override.
      actions = actions.map((item) =>
        item.action === "user_created" ? { ...item, enabled: categories[0]!.enabled } : item
      );
      return ok({ categories: structuredClone(categories) });
    }
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function open() {
  const result = renderInApp(<AuditConfig />);
  await screen.findByRole("checkbox", { name: "Administratörsåtgärder" });
  return result;
}
const toggleCategory = () =>
  fireEvent.click(screen.getByRole("checkbox", { name: "Administratörsåtgärder" }));
const save = () => fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));
const reset = () => fireEvent.click(screen.getByRole("button", { name: "Återställ" }));
const enabled = (label: string) =>
  String((screen.getByRole("checkbox", { name: label }) as HTMLInputElement).checked);

describe("AuditConfig", () => {
  it("keeps Save focused and ignores another submit while its action request runs", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Användare skapad" }));
    let finish!: (value: unknown) => void;
    api.PATCH.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const button = screen.getByRole("button", { name: "Spara ändringar" });
    button.focus();
    fireEvent.click(button);
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(button);
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    await act(async () =>
      finish({
        data: {
          actions: actions.map((item) =>
            item.action === "user_created" ? { ...item, enabled: false } : item
          )
        },
        response: new Response()
      })
    );
    await waitFor(() => expect(screen.queryByText("Du har osparade ändringar")).toBeNull());
    expect(document.activeElement).toBe(button);
  });
  it("keeps unedited actions fresh without writing over another administrator's changes", async () => {
    const { queryClient } = await open();
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Användare skapad" }));
    actions = actions.map((item) =>
      item.action === "user_deleted" ? { ...item, enabled: false } : item
    );
    await act(() => queryClient.invalidateQueries({ queryKey: AUDIT_ACTION_CONFIG_KEY }));
    await waitFor(() => expect(enabled("Användare borttagen")).toBe("false"));
    save();
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/audit/config/actions", {
      body: { updates: [{ action: "user_created", enabled: false }] }
    });
  });
  it("shows descriptions, expands/collapses and stages toggles until Save or Reset", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    expect(screen.getByText("Loggar när en ny användare skapas")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Användare skapad" }));
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(screen.getByText("inaktiverad")).toBeTruthy();
    reset();
    expect(enabled("Användare skapad")).toBe("true");
    expect(api.PATCH).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stäng alla" }));
    expect(screen.queryByRole("checkbox", { name: "Användare skapad" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("sends category then its full intended child states and accepts the real responses", async () => {
    await open();
    toggleCategory();
    save();
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
    expect(api.PATCH.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/audit/config",
      "/api/v1/audit/config/actions"
    ]);
    expect(api.PATCH.mock.calls[1]?.[1]).toEqual({
      body: {
        updates: [
          { action: "user_created", enabled: false },
          { action: "user_deleted", enabled: false }
        ]
      }
    });
    await waitFor(() => expect(screen.queryByText("Du har osparade ändringar")).toBeNull());
    // Initial reads only; successful PATCH responses already contain the actual state.
    expect(api.GET).toHaveBeenCalledTimes(2);
  });

  it("does not write actions when the category save fails and keeps edits for retry", async () => {
    await open();
    failCategory = true;
    toggleCategory();
    save();
    await screen.findByText("Det gick inte att spara konfigurationen");
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    expect(enabled("Administratörsåtgärder")).toBe("false");
    failCategory = false;
    save();
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByText("Du har osparade ändringar")).toBeNull());
  });

  it("keeps remaining intent after partial save and resets to refreshed effective actions", async () => {
    await open();
    failActions = true;
    toggleCategory();
    save();
    await screen.findByText("Konfigurationen sparades delvis");
    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(4));
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    expect(enabled("Användare skapad")).toBe("false");
    expect(enabled("Användare borttagen")).toBe("false");
    reset();
    expect(enabled("Administratörsåtgärder")).toBe("false");
    expect(enabled("Användare skapad")).toBe("false");
    expect(enabled("Användare borttagen")).toBe("true");
    expect(api.PATCH).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Du har osparade ändringar")).toBeNull();
  });

  it("retries only remaining actions after a partial save", async () => {
    await open();
    failActions = true;
    toggleCategory();
    save();
    await screen.findByText("Konfigurationen sparades delvis");
    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(4));
    failActions = false;
    save();
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(3));
    expect(api.PATCH.mock.calls[2]).toEqual([
      "/api/v1/audit/config/actions",
      { body: { updates: [{ action: "user_deleted", enabled: false }] } }
    ]);
    await waitFor(() => expect(screen.queryByText("Du har osparade ändringar")).toBeNull());
  });

  it("preserves the draft when reconciliation fails and requires a fresh baseline before Reset", async () => {
    await open();
    failActions = true;
    failRefresh = true;
    toggleCategory();
    save();
    await screen.findByText("Serverläget kunde inte läsas om. Dina ändringar finns kvar.", {
      selector: "p"
    });
    expect(screen.getByRole("button", { name: "Återställ" })).toHaveProperty("disabled", true);
    expect(enabled("Administratörsåtgärder")).toBe("false");
    failRefresh = false;
    fireEvent.click(
      screen.getByRole("button", { name: /Försök igen: Innehållet kunde inte uppdateras/ })
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Återställ" })).toHaveProperty("disabled", false)
    );
    reset();
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    expect(enabled("Användare borttagen")).toBe("true");
  });

  it("uses server-normalized action values without leaving a false unsaved state", async () => {
    await open();
    normalize = true;
    fireEvent.click(screen.getByRole("button", { name: "Expandera alla" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Användare skapad" }));
    save();
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(enabled("Användare skapad")).toBe("true"));
    expect(screen.queryByText("Du har osparade ändringar")).toBeNull();
  });
});
