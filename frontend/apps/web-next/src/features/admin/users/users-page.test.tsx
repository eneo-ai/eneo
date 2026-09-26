// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const searchParams = vi.hoisted(() => ({ value: "role_id=custom" }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("sonner", () => ({ toast }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchParams.value)
}));
vi.mock("./user-editor", () => ({ UserEditorDialog: () => null }));

import { AdminUsersPage } from "./users-page";

/** The signed-in admin: not a user in the lists below. */
const appContext = testAppContext({ user: { id: "me" } });

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

const user = (overrides: Record<string, unknown>) => ({
  id: "u1",
  email: "anna.lind@kommun.se",
  username: "anna.lind",
  used_tokens: 0,
  email_verified: true,
  quota_limit: null,
  is_active: true,
  state: "active",
  roles: [{ id: "custom", name: "Manager", permissions: [] }],
  user_groups: [],
  ...overrides
});

const users = [
  user({}),
  user({
    id: "u2",
    email: "per.berg@kommun.se",
    username: null,
    state: "invited",
    roles: []
  })
];

type Page = { items: unknown[]; totalPages?: number; page?: number };

/** Answers the users endpoint with `pages(query)`, the roles endpoint with one role. */
function serve(pages: (query: Record<string, unknown>) => Page) {
  api.GET.mockImplementation(
    (path: string, init?: { params?: { query?: Record<string, unknown> } }) => {
      if (path === "/api/v1/roles/") {
        return ok({
          roles: { items: [{ id: "custom", name: "Manager", permissions: [] }] },
          predefined_roles: { items: [] }
        });
      }
      const query = init?.params?.query ?? {};
      const { items, totalPages = 1, page = Number(query.page) } = pages(query);
      return ok({
        items,
        metadata: {
          page,
          total_pages: totalPages,
          total_count: items.length,
          counts: { active: 1, inactive: 3 },
          has_next: page < totalPages,
          has_previous: page > 1
        }
      });
    }
  );
}

function renderPage(items: unknown[] = []) {
  serve(() => ({ items }));
  return renderInApp(<AdminUsersPage />, { appContext });
}

function usersQuery(overrides: Record<string, unknown>) {
  return {
    params: {
      query: {
        page: 1,
        page_size: 100,
        search_email: undefined,
        state_filter: "active",
        role_id: undefined,
        ...overrides
      }
    }
  };
}

function liveRegion() {
  return document.querySelector("[data-astryx-live-region='polite']")?.textContent ?? "";
}

afterEach(() => {
  cleanup();
  // Astryx keeps one live region on <body> (re-created on the next announce):
  // no announcement may carry over into the next test.
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  vi.clearAllMocks();
  searchParams.value = "role_id=custom";
});

describe("AdminUsersPage", () => {
  it("filters users by the selected role and can return to all users", async () => {
    renderPage();
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith(
        "/api/v1/admin/users/",
        usersQuery({ role_id: "custom" })
      )
    );
    expect(await screen.findByText("Manager")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visa alla användare" }));
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/users/", usersQuery({}))
    );
  });

  it("lists users with avatar, roles, status and a named row menu", async () => {
    searchParams.value = "";
    renderPage(users);

    const table = await screen.findByRole("table", { name: "Aktiva användare" });
    const [, anna, per] = within(table).getAllByRole("row");
    expect(within(anna!).getByText("anna.lind")).toBeTruthy();
    expect(within(anna!).getByText("anna.lind@kommun.se")).toBeTruthy();
    expect(within(anna!).getByTitle("Manager")).toBeTruthy();
    expect(within(anna!).getByText("Aktiv")).toBeTruthy();
    expect(
      within(anna!).getByRole("button", { name: "Fler åtgärder för anna.lind@kommun.se" })
    ).toBeTruthy();
    // Without a username the email is the name.
    expect(within(per!).getByText("per.berg@kommun.se")).toBeTruthy();
    expect(within(per!).getByText("Inbjuden")).toBeTruthy();

    expect(screen.getByRole("heading", { level: 1, name: "Användare" })).toBeTruthy();
    // The breadcrumb names the section as the admin navigation does.
    expect(screen.getByText("Användare och åtkomst")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Sök användare på e-post" })).toBeTruthy();
    expect(screen.getByText("2 användare")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("switches between active and inactive users with the tabs", async () => {
    searchParams.value = "";
    renderPage(users);
    const inactive = await screen.findByRole("tab", { name: "Inaktiva användare 3" });
    expect(
      screen.getByRole("tab", { name: "Aktiva användare 1" }).getAttribute("aria-selected")
    ).toBe("true");

    fireEvent.click(inactive);

    expect(inactive.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(inactive.id);
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith(
        "/api/v1/admin/users/",
        usersQuery({ state_filter: "inactive" })
      )
    );
  });

  it("announces the result count of a search once its results are in", async () => {
    searchParams.value = "";
    serve((query) => ({ items: query.search_email ? [users[0]] : users }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("2 användare");
    // Not on first load.
    expect(liveRegion()).toBe("");

    fireEvent.change(screen.getByRole("textbox", { name: "Sök användare på e-post" }), {
      target: { value: "anna" }
    });

    await waitFor(() => expect(liveRegion()).toBe("1 användare"), { timeout: 2000 });
    expect(screen.getByText("1 användare", { selector: "p" })).toBeTruthy();
  });
});

describe("AdminUsersPage paging", () => {
  beforeEach(() => {
    searchParams.value = "";
  });

  it("keeps the pressed page button enabled and focused while the page loads", async () => {
    let release: () => void = () => {};
    serve((query) => ({ items: [user({ email: `sida${query.page}@kommun.se` })], totalPages: 3 }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("sida1@kommun.se");

    // Page 2 answers only when released: the list is still loading.
    const pending = new Promise<void>((resolve) => (release = resolve));
    const serveNow = api.GET.getMockImplementation()!;
    api.GET.mockImplementation(async (path: string, init: unknown) => {
      if (path === "/api/v1/admin/users/") await pending;
      return serveNow(path, init);
    });
    const page2 = screen.getByRole("button", { name: "Gå till sida 2" });
    page2.focus();
    fireEvent.click(page2);

    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/users/", usersQuery({ page: 2 }))
    );
    expect(page2.hasAttribute("disabled")).toBe(false);
    expect(page2.getAttribute("aria-current")).toBe("page");
    expect(document.activeElement).toBe(page2);

    await act(async () => release());
    expect(await screen.findByText("sida2@kommun.se")).toBeTruthy();
    expect(document.activeElement).toBe(page2);
  });

  it("moves focus to the list when the next-page button disables at the last page", async () => {
    serve((query) => ({ items: [user({ email: `sida${query.page}@kommun.se` })], totalPages: 2 }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("sida1@kommun.se");

    const next = screen.getByRole("button", { name: "Gå till nästa sida" });
    next.focus();
    fireEvent.click(next);

    expect(await screen.findByText("sida2@kommun.se")).toBeTruthy();
    expect(next.hasAttribute("disabled")).toBe(true);
    // Browsers move focus to <body> when the focused element becomes disabled
    // ("focus fixup"); jsdom keeps it there, so do what the browser does.
    act(() => {
      document.body.tabIndex = -1;
      document.body.focus();
      document.body.removeAttribute("tabindex");
    });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });

  it("shows the last page instead of an empty one when the page runs past the end", async () => {
    searchParams.value = "page=4";
    serve((query) =>
      Number(query.page) > 2
        ? { items: [], totalPages: 2 }
        : { items: [user({ email: `sida${query.page}@kommun.se` })], totalPages: 2 }
    );
    renderInApp(<AdminUsersPage />, { appContext });

    expect(await screen.findByText("sida2@kommun.se")).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/users/", usersQuery({ page: 2 }));
  });

  it("fits a phone: page x of y instead of page numbers below the sm breakpoint", async () => {
    setViewport("phone");
    serve(() => ({ items: users, totalPages: 12 }));
    renderInApp(<AdminUsersPage />, { appContext });

    const pagination = await screen.findByRole("navigation", { name: "Sidnumrering" });
    expect(within(pagination).getByText("Sida 1 av 12")).toBeTruthy();
    expect(within(pagination).queryByRole("button", { name: "Gå till sida 2" })).toBeNull();
  });
});

describe("AdminUsersPage row actions", () => {
  beforeEach(() => {
    searchParams.value = "";
    api.POST.mockImplementation(() => ok({}));
    api.DELETE.mockImplementation(() => ok({}));
  });

  function openRowMenu(email: string) {
    const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${email}` });
    trigger.focus();
    // jsdom does not turn Enter into a click; Astryx opens menus on the key.
    fireEvent.keyDown(trigger, { key: "Enter" });
    return document.getElementById(trigger.getAttribute("aria-controls")!)!;
  }

  it("deactivates a user, confirms it and keeps focus in the list", async () => {
    let list = users;
    serve(() => ({ items: list }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("anna.lind@kommun.se");

    list = users.slice(1); // The deactivated user leaves the active tab.
    fireEvent.click(
      within(openRowMenu("anna.lind@kommun.se")).getByRole("menuitem", {
        name: "Avaktivera användare"
      })
    );

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/{username}/deactivate", {
        params: { path: { username: "anna.lind" } }
      })
    );
    expect(toast.success).toHaveBeenCalledWith("anna.lind@kommun.se avaktiverades");
    await waitFor(() => expect(screen.queryByText("anna.lind@kommun.se")).toBeNull());
    // The focused row is gone: focus moves to the list's panel, not <body>.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });

  it("does not let admins deactivate or delete themselves", async () => {
    serve(() => ({ items: [user({ id: "me" })] }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("anna.lind@kommun.se");

    const menu = openRowMenu("anna.lind@kommun.se");
    for (const name of ["Avaktivera användare", "Radera användare"]) {
      expect(within(menu).getByRole("menuitem", { name }).getAttribute("aria-disabled")).toBe(
        "true"
      );
    }
  });

  it("reactivates an inactive user", async () => {
    searchParams.value = "tab=inactive";
    serve(() => ({ items: [user({ state: "inactive", is_active: false })] }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("anna.lind@kommun.se");

    fireEvent.click(
      within(openRowMenu("anna.lind@kommun.se")).getByRole("menuitem", {
        name: "Återaktivera användare"
      })
    );

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/admin/users/{username}/reactivate", {
        params: { path: { username: "anna.lind" } }
      })
    );
    expect(toast.success).toHaveBeenCalledWith("anna.lind@kommun.se återaktiverades");
  });

  it("deletes a user after confirmation", async () => {
    let list = users;
    serve(() => ({ items: list }));
    renderInApp(<AdminUsersPage />, { appContext });
    await screen.findByText("per.berg@kommun.se");

    fireEvent.click(
      within(openRowMenu("per.berg@kommun.se")).getByRole("menuitem", {
        name: "Radera användare"
      })
    );
    const dialog = await screen.findByRole("alertdialog", { name: "Radera användare" });
    expect(within(dialog).getByText(/per\.berg@kommun\.se/)).toBeTruthy();
    list = users.slice(0, 1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/users/admin/{id}/", {
        params: { path: { id: "u2" } }
      })
    );
    expect(toast.success).toHaveBeenCalledWith("per.berg@kommun.se raderades");
    await waitFor(() => expect(screen.queryByText("per.berg@kommun.se")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tabpanel")), {
      timeout: 1500
    });
  });
});
