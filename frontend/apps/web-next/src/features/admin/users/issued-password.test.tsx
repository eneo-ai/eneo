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
});
