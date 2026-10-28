// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => ({
  useSearchParams: () => new URLSearchParams("search_name=bo.e")
}));

import { AdminUsersPage } from "./users-page";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const bo = {
  id: "user-2",
  email: "bo.ek@kommun.se",
  username: "bo.ek",
  used_tokens: 0,
  email_verified: true,
  quota_limit: null,
  is_active: true,
  state: "active",
  roles: [],
  user_groups: []
};

/** The users the username filter "bo.e" matches: Bo, until he is renamed. */
function serve() {
  let matching = [bo];
  api.GET.mockImplementation((path: string) => {
    switch (path) {
      case "/api/v1/admin/users/":
        return ok({
          items: matching,
          metadata: {
            page: 1,
            page_size: 100,
            total_pages: 1,
            total_count: matching.length,
            counts: { active: 1, inactive: 0 },
            has_next: false,
            has_previous: false
          }
        });
      case "/api/v1/users/password-policy/":
        return ok({
          min_length: 12,
          max_bytes: 72,
          requires_uppercase: false,
          requires_lowercase: false,
          requires_number: true,
          requires_symbol: false
        });
      case "/api/v1/roles/":
        return ok({ roles: { items: [] }, predefined_roles: { items: [] } });
      case "/api/v1/user-groups/":
        return ok({ items: [] });
      default:
        return ok({ max_age_days: null });
    }
  });
  return {
    dropRenamed() {
      matching = [];
    }
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminUsersPage issued password", () => {
  it("keeps the one-time password on screen when a refetch drops the edited user's row", async () => {
    const backend = serve();
    api.POST.mockImplementation(() => ok({}));
    const { queryClient } = renderInApp(<AdminUsersPage />, {
      appContext: testAppContext({ user: { id: "me" } })
    });
    const trigger = await screen.findByRole("button", {
      name: "Fler åtgärder för bo.ek@kommun.se"
    });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Redigera användare" }));

    const editor = await screen.findByRole("dialog", { name: "Redigera användare" });
    await within(editor).findByRole("switch", { name: /^Generera ett nytt lösenord/ });
    fireEvent.change(within(editor).getByLabelText(/^Användarnamn/), {
      target: { value: "bo.lind" }
    });
    fireEvent.click(within(editor).getByRole("switch", { name: /^Generera ett nytt lösenord/ }));
    fireEvent.click(within(editor).getByRole("button", { name: "Spara ändringar" }));

    const reveal = await screen.findByRole("dialog", { name: "Nytt lösenord har satts" });
    const body = (api.POST.mock.calls[0]?.[1] as { body: { password: string; username: string } })
      .body;
    expect(body.username).toBe("bo.lind");
    within(reveal).getByText(body.password);

    // A refetch (window focus, say) no longer finds the renamed user under the filter.
    backend.dropRenamed();
    await act(() => queryClient.invalidateQueries({ queryKey: ["admin-users"] }));
    await waitFor(() => expect(screen.queryByText("bo.ek@kommun.se")).toBeNull());

    expect(screen.getByRole("dialog", { name: "Nytt lösenord har satts" })).toBe(reveal);
    within(reveal).getByText(body.password);
  });

  it("shows a reset's password even when the row went while the reset saved", async () => {
    const backend = serve();
    let settle: () => void = () => {};
    api.POST.mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = () => resolve({ data: {}, response: new Response("{}") });
        })
    );
    const { queryClient } = renderInApp(<AdminUsersPage />, {
      appContext: testAppContext({ user: { id: "me" } })
    });
    const trigger = await screen.findByRole("button", {
      name: "Fler åtgärder för bo.ek@kommun.se"
    });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Redigera användare" }));
    const editor = await screen.findByRole("dialog", { name: "Redigera användare" });
    fireEvent.click(
      await within(editor).findByRole("switch", { name: /^Generera ett nytt lösenord/ })
    );
    fireEvent.click(within(editor).getByRole("button", { name: "Spara ändringar" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));

    // The row, and the editor in it, go while the save is still running.
    backend.dropRenamed();
    await act(() => queryClient.invalidateQueries({ queryKey: ["admin-users"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await act(async () => settle());
    const password = (api.POST.mock.calls[0]?.[1] as { body: { password: string } }).body.password;
    within(await screen.findByRole("dialog", { name: "Nytt lösenord har satts" })).getByText(
      password
    );
  });

  /**
   * Bo's password reset and a new account save at the same time (the reset's
   * editor closed while it saved): each password is shown in turn, in the
   * order the saves land, and none replaces one not yet handed over.
   */
  async function overlappingSaves(order: "reset first" | "create first") {
    serve();
    const settle: Record<string, () => void> = {};
    api.POST.mockImplementation(
      (path: string) =>
        new Promise((resolve) => {
          settle[path] = () => resolve({ data: {}, response: new Response("{}") });
        })
    );
    renderInApp(<AdminUsersPage />, { appContext: testAppContext({ user: { id: "me" } }) });

    const trigger = await screen.findByRole("button", {
      name: "Fler åtgärder för bo.ek@kommun.se"
    });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Redigera användare" }));
    const editor = await screen.findByRole("dialog", { name: "Redigera användare" });
    fireEvent.click(
      await within(editor).findByRole("switch", { name: /^Generera ett nytt lösenord/ })
    );
    fireEvent.click(within(editor).getByRole("button", { name: "Spara ändringar" }));
    await waitFor(() => expect(settle["/api/v1/admin/users/{username}/"]).toBeDefined());
    fireEvent.click(within(editor).getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Skapa användare" }));
    const create = await screen.findByRole("dialog", { name: "Skapa en ny användare" });
    await within(create).findByText(/Eneo genererar ett lösenord/);
    fireEvent.change(within(create).getByLabelText(/^Användarnamn/), {
      target: { value: "eva.ek" }
    });
    fireEvent.change(within(create).getByLabelText(/^E-post/), {
      target: { value: "eva.ek@kommun.se" }
    });
    fireEvent.click(within(create).getByRole("button", { name: "Skapa användare" }));
    await waitFor(() => expect(settle["/api/v1/admin/users/"]).toBeDefined());

    const passwordFor = (path: string) =>
      (
        api.POST.mock.calls.find((call) => call[0] === path)?.[1] as {
          body: { password: string };
        }
      ).body.password;
    const reset = {
      title: "Nytt lösenord har satts",
      password: passwordFor("/api/v1/admin/users/{username}/")
    };
    const created = {
      title: "Kontot har skapats",
      password: passwordFor("/api/v1/admin/users/")
    };
    const [first, second] = order === "reset first" ? [reset, created] : [created, reset];
    const paths =
      order === "reset first"
        ? ["/api/v1/admin/users/{username}/", "/api/v1/admin/users/"]
        : ["/api/v1/admin/users/", "/api/v1/admin/users/{username}/"];

    await act(async () => settle[paths[0]!]!());
    const shown = await screen.findByRole("dialog", { name: first.title });
    within(shown).getByText(first.password);
    await act(async () => settle[paths[1]!]!());
    // The first is still the one on screen, not replaced.
    expect(screen.getByRole("dialog", { name: first.title })).toBeTruthy();
    within(screen.getByRole("dialog", { name: first.title })).getByText(first.password);

    fireEvent.click(within(shown).getByRole("button", { name: "Klar" }));
    const next = await screen.findByRole("dialog", { name: second.title });
    within(next).getByText(second.password);
  }

  it("shows a reset's and a new account's passwords in turn when the reset lands first", () =>
    overlappingSaves("reset first"));

  it("shows a reset's and a new account's passwords in turn when the account lands first", () =>
    overlappingSaves("create first"));
});
