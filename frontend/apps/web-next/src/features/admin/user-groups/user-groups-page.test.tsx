// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

import { AdminUserGroupsPage } from "./user-groups-page";

const appContext = testAppContext({ permissions: ["admin"] });

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const anna = { id: "u1", email: "anna.lind@kommun.se", username: "anna.lind" };
const per = { id: "u2", email: "per.berg@kommun.se", username: null };
const eva = { id: "u3", email: "eva.ek@kommun.se", username: "eva.ek" };

type Group = { id: string; name: string; users: (typeof anna | typeof per)[] };

/**
 * The backend: groups (changed by the test as the requests land) and the user
 * directory, filtered by the e-mail search as the backend does.
 */
function serve(initial: Group[], directory = [anna, per, eva]) {
  let groups = initial;
  api.GET.mockImplementation((path: string, init?: { params?: { query?: { email?: string } } }) => {
    if (path === "/api/v1/user-groups/") return ok({ items: groups, count: groups.length });
    if (path === "/api/v1/users/") {
      const email = init?.params?.query?.email;
      const items = email ? directory.filter((user) => user.email.includes(email)) : directory;
      return ok({ items, total_count: items.length, next_cursor: null });
    }
    throw new Error(`unexpected GET ${path}`);
  });
  return {
    set(next: Group[]) {
      groups = next;
    }
  };
}

async function renderPage(groups: Group[], directory?: (typeof anna | typeof per)[]) {
  const backend = serve(groups, directory);
  const { queryClient } = renderInApp(<AdminUserGroupsPage />, { appContext });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  if (groups.length > 0) await screen.findByRole("table", { name: "Användargrupper" });
  return { backend, invalidate };
}

function openRowMenu(name: string) {
  const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
  trigger.focus();
  // jsdom does not turn Enter into a click; Astryx opens menus on the key.
  fireEvent.keyDown(trigger, { key: "Enter" });
  return document.getElementById(trigger.getAttribute("aria-controls")!)!;
}

function expectRefreshed(invalidate: ReturnType<typeof vi.spyOn>) {
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["user-groups"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-users"] });
}

const economy: Group = { id: "g1", name: "Ekonomi", users: [anna, per] };
const support: Group = { id: "g2", name: "Arkiv", users: [] };

afterEach(() => {
  cleanup();
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  vi.clearAllMocks();
});

beforeEach(() => {
  api.POST.mockImplementation(() => ok({ id: "new", name: "x", users: [] }));
  api.DELETE.mockImplementation(() => ok({}));
});

describe("AdminUserGroupsPage", () => {
  /** The group names, in the order the table's rows show them. */
  const rowNames = () =>
    screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getByText(/^(Arkiv|Ekonomi|Bygglov)$/).textContent);

  it("lists the groups by name with their member counts and a named row menu", async () => {
    // Name order and member-count order differ, so the two sorts can be told apart.
    await renderPage([
      { id: "g1", name: "Ekonomi", users: [anna] },
      { id: "g2", name: "Arkiv", users: [anna, per, eva] },
      { id: "g3", name: "Bygglov", users: [] }
    ]);

    expect(screen.getByRole("heading", { level: 1, name: "Användargrupper" })).toBeTruthy();
    expect(rowNames()).toEqual(["Arkiv", "Bygglov", "Ekonomi"]);
    const [, arkiv] = screen.getAllByRole("row");
    expect(within(arkiv!).getByText("3 medlemmar")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Ekonomi" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("sorts the groups by member count from the Members column", async () => {
    await renderPage([
      { id: "g1", name: "Ekonomi", users: [anna] },
      { id: "g2", name: "Arkiv", users: [anna, per, eva] },
      { id: "g3", name: "Bygglov", users: [] }
    ]);
    const members = screen.getByRole("columnheader", { name: /Medlemmar/ });

    fireEvent.click(within(members).getByRole("button"));
    await waitFor(() => expect(rowNames()).toEqual(["Bygglov", "Ekonomi", "Arkiv"]));

    fireEvent.click(within(members).getByRole("button"));
    await waitFor(() => expect(rowNames()).toEqual(["Arkiv", "Ekonomi", "Bygglov"]));
  });

  it("offers to create the first group when there is none", async () => {
    await renderPage([]);
    expect(await screen.findByText(/inga användargrupper konfigurerade/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa användargrupp" })).toHaveLength(2);
  });

  it("creates a group, saying at the field when the name is missing", async () => {
    const { invalidate } = await renderPage([economy]);
    fireEvent.click(screen.getByRole("button", { name: "Skapa användargrupp" }));
    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny användargrupp" });
    const name = within(dialog).getByRole("textbox", { name: /^Gruppnamn/ });

    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa användargrupp" }));

    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(api.POST).not.toHaveBeenCalled();

    api.POST.mockImplementation(() => ok({ id: "g3", name: "Bygglov", users: [] }));
    fireEvent.change(name, { target: { value: "  Bygglov " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa användargrupp" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/", { body: { name: "Bygglov" } })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Gruppen Bygglov skapades");
    expectRefreshed(invalidate);
  });

  it("renames a group from its row menu", async () => {
    const { invalidate } = await renderPage([economy]);
    fireEvent.click(within(openRowMenu("Ekonomi")).getByRole("menuitem", { name: "Byt namn" }));
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på användargrupp" });
    const name = within(dialog).getByRole("textbox", { name: /^Gruppnamn/ }) as HTMLInputElement;
    expect(name.value).toBe("Ekonomi");

    api.POST.mockImplementation(() => ok({ ...economy, name: "Ekonomistaben" }));
    fireEvent.change(name, { target: { value: "Ekonomistaben" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara ändringar" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/{id}/", {
        params: { path: { id: "g1" } },
        body: { name: "Ekonomistaben" }
      })
    );
    expect(toast.success).toHaveBeenCalledWith("Gruppen heter nu Ekonomistaben");
    expectRefreshed(invalidate);
  });

  it("deletes a group after a confirmation that names it, then focuses the heading", async () => {
    const { backend } = await renderPage([economy, support]);
    fireEvent.click(
      within(openRowMenu("Ekonomi")).getByRole("menuitem", { name: "Radera användargrupp" })
    );
    const confirm = await screen.findByRole("alertdialog", { name: "Radera användargrupp" });
    expect(within(confirm).getByText(/Vill du radera gruppen Ekonomi\?/)).toBeTruthy();

    backend.set([support]);
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/user-groups/{id}/", {
        params: { path: { id: "g1" } }
      })
    );
    await waitFor(() => expect(screen.queryByText("Ekonomi")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Gruppen Ekonomi raderades");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { level: 1, name: "Användargrupper" })
      )
    );
  });
});

describe("AdminUserGroupsPage members", () => {
  async function openMembers(groups: Group[], directory?: (typeof anna | typeof per)[]) {
    const page = await renderPage(groups, directory);
    fireEvent.click(
      within(openRowMenu("Ekonomi")).getByRole("menuitem", { name: "Hantera medlemmar" })
    );
    const dialog = await screen.findByRole("dialog", { name: "Hantera medlemmar i Ekonomi" });
    if (directory?.length !== 0) {
      await within(dialog).findByRole("checkbox", { name: /eva\.ek@kommun\.se/ });
    }
    return { ...page, dialog };
  }

  it("lists members with their usernames, and users who are members cannot be ticked", async () => {
    const { dialog } = await openMembers([{ ...economy, users: [anna] }]);

    const annaBox = within(dialog).getByRole("checkbox", { name: /anna\.lind@kommun\.se/ });
    expect(
      annaBox.hasAttribute("disabled") || annaBox.getAttribute("aria-disabled") === "true"
    ).toBe(true);
    expect(within(dialog).getByText(/Redan tillagd/)).toBeTruthy();
    const members = within(dialog).getByRole("heading", { name: "Nuvarande medlemmar (1)" });
    expect(members).toBeTruthy();
    expect(
      within(dialog).getByRole("button", { name: "Ta bort anna.lind@kommun.se från gruppen" })
    ).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("keeps the users ticked across searches and adds them together", async () => {
    const { dialog, backend } = await openMembers([{ ...economy, users: [] }]);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /per\.berg@kommun\.se/ }));

    // A search that hides Per: the e-mail goes to the backend, and Per stays picked.
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Sök användare på e-post" }), {
      target: { value: "eva" }
    });
    await waitFor(() =>
      expect(within(dialog).queryByRole("checkbox", { name: /per\.berg@kommun\.se/ })).toBeNull()
    );
    expect(api.GET).toHaveBeenCalledWith("/api/v1/users/", {
      params: { query: { email: "eva", limit: 100, cursor: undefined } },
      signal: expect.any(AbortSignal)
    });
    expect(within(dialog).getByRole("list", { name: "Valda användare" }).textContent).toContain(
      "per.berg@kommun.se"
    );
    fireEvent.click(await within(dialog).findByRole("checkbox", { name: /eva\.ek@kommun\.se/ }));
    const add = within(dialog).getByRole("button", { name: /^Lägg till valda/ });
    expect(add.textContent).toContain("(2)");

    backend.set([{ ...economy, users: [per, eva] }]);
    fireEvent.click(add);

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect(
      api.POST.mock.calls.map(
        (call) => (call[1] as { params: { path: { user_id: string } } }).params.path.user_id
      )
    ).toEqual(["u2", "u3"]);
  });

  it("adds several users at once", async () => {
    const { dialog, backend, invalidate } = await openMembers([{ ...economy, users: [anna] }]);
    const add = () => within(dialog).getByRole("button", { name: /^Lägg till valda/ });

    // Nothing ticked: pressing says so and sends nothing.
    fireEvent.click(add());
    expect(await within(dialog).findByText("Välj en användare i listan.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: /per\.berg@kommun\.se/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /eva\.ek@kommun\.se/ }));
    expect(add().textContent).toContain("Lägg till valda (2)");

    backend.set([{ ...economy, users: [anna, per, eva] }]);
    fireEvent.click(add());

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
      params: { path: { id: "g1", user_id: "u2" } }
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
      params: { path: { id: "g1", user_id: "u3" } }
    });
    expect(
      await within(dialog).findByRole("heading", { name: "Nuvarande medlemmar (3)" })
    ).toBeTruthy();
    expect(add().textContent).toContain("Lägg till valda (0)");
    expectRefreshed(invalidate);
  });

  it("keeps the users that could not be added ticked for a retry", async () => {
    const { dialog, backend } = await openMembers([{ ...economy, users: [] }]);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /per\.berg@kommun\.se/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /eva\.ek@kommun\.se/ }));
    api.POST.mockImplementationOnce(() => ok({})).mockImplementationOnce(() =>
      Promise.resolve({
        error: { message: "Boom" },
        response: new Response(null, { status: 500 })
      })
    );
    backend.set([{ ...economy, users: [per] }]);

    fireEvent.click(within(dialog).getByRole("button", { name: /^Lägg till valda/ }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(
      await within(dialog).findByRole("heading", { name: "Nuvarande medlemmar (1)" })
    ).toBeTruthy();
    const eve = within(dialog).getByRole("checkbox", { name: /eva\.ek@kommun\.se/ });
    expect((eve as HTMLInputElement).checked).toBe(true);
    expect(within(dialog).getByRole("button", { name: /^Lägg till valda/ }).textContent).toContain(
      "(1)"
    );

    // Per, who was added, is removed again: he must not come back ticked, nor
    // be re-added by the retry.
    backend.set([{ ...economy, users: [] }]);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Ta bort per.berg@kommun.se från gruppen" })
    );
    expect(
      await within(dialog).findByRole("heading", { name: "Nuvarande medlemmar (0)" })
    ).toBeTruthy();
    const perBox = within(dialog).getByRole("checkbox", { name: /per\.berg@kommun\.se/ });
    expect((perBox as HTMLInputElement).checked).toBe(false);

    api.POST.mockClear();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Lägg till valda/ }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
      params: { path: { id: "g1", user_id: "u3" } }
    });
  });

  it("says at the search field that a user must be chosen when none is found", async () => {
    const { dialog } = await openMembers([economy], []);
    expect(await within(dialog).findByText("Inga användare hittades")).toBeTruthy();
    const search = within(dialog).getByRole("textbox", { name: "Sök användare på e-post" });

    fireEvent.click(within(dialog).getByRole("button", { name: /^Lägg till valda/ }));

    await waitFor(() => expect(document.activeElement).toBe(search));
    expect(search.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText("Välj en användare i listan.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("removes a member at once", async () => {
    const { dialog, backend, invalidate } = await openMembers([economy]);
    backend.set([{ ...economy, users: [per] }]);

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Ta bort anna.lind@kommun.se från gruppen" })
    );

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/user-groups/{id}/users/{user_id}/", {
        params: { path: { id: "g1", user_id: "u1" } }
      })
    );
    expect(
      await within(dialog).findByRole("heading", { name: "Nuvarande medlemmar (1)" })
    ).toBeTruthy();
    expectRefreshed(invalidate);
  });
});
