// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import type { Space } from "@/features/spaces/space";
import { makeMember, makeSpace } from "@/features/spaces/testing/space-fixture";

const ok = () => Promise.resolve({ data: {}, response: new Response("{}") });
const api = vi.hoisted(() => ({
  GET: vi.fn<
    (path: string, options?: unknown) => Promise<{ data: { items: unknown[] }; response: Response }>
  >(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn()
}));
const state = vi.hoisted(() => ({ space: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});

import { SpaceMembers } from "./space-members";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
beforeEach(() => {
  state.space = makeSpace();
  api.GET.mockReset().mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
  api.POST.mockImplementation(ok);
  api.PATCH.mockImplementation(ok);
  api.DELETE.mockImplementation(ok);
});
afterEach(() => vi.clearAllMocks());

const EVERYTHING = ["read", "create", "edit", "delete", "add", "publish"];

/** Anna (the signed-in user, admin), Erik (editor), Sofia (viewer, with a username) and a group. */
function spaceWithMembers(permissions = EVERYTHING) {
  return makeSpace({
    resourcePermissions: permissions as never,
    members: [
      makeMember(),
      makeMember({ id: "u2", email: "erik.johansson@example.com", role: "editor" }),
      makeMember({ id: "u3", email: "sofia.n@example.com", username: "sofia", role: "viewer" })
    ],
    overrides: {
      group_members: {
        items: [{ id: "g1", name: "Bygglovsenheten", role: "viewer", user_count: 12 }],
        count: 1,
        permissions
      }
    }
  });
}

async function openDialog(trigger: string) {
  renderInApp(<SpaceMembers />);
  fireEvent.click(screen.getAllByRole("button", { name: trigger })[0]!);
  const dialog = await screen.findByRole("dialog", { name: trigger });
  return { dialog, add: within(dialog).getByRole("button", { name: trigger }) };
}

it("says a user must be picked when adding a member, at the search field", async () => {
  const { dialog, add } = await openDialog("Lägg till medlem");
  // Never disabled: a disabled button says nothing about what is missing.
  expect((add as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(add);

  const search = within(dialog).getByLabelText("E-post");
  expect(search.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(search.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Välj en användare i listan."
  );
  expect(document.activeElement).toBe(search);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
});

it("pages through users and keeps existing members visible but unavailable for adding", async () => {
  state.space = spaceWithMembers();
  api.GET.mockImplementation((path, options) => {
    const cursor = (options as { params?: { query?: { cursor?: string } } })?.params?.query?.cursor;
    return Promise.resolve({
      data:
        path === "/api/v1/users/"
          ? {
              items: cursor
                ? [{ id: "u4", email: "new@example.se", username: "Ny" }]
                : [makeMember()],
              total_count: 2,
              next_cursor: cursor ? null : "next-users"
            }
          : { items: [] },
      response: new Response("{}")
    });
  });
  const { dialog, add } = await openDialog("Lägg till medlem");
  const existing = await within(dialog).findByRole("radio", { name: "anna.lind@example.com" });
  expect((existing as HTMLInputElement).disabled).toBe(true);
  expect(within(dialog).getByText("Redan tillagd")).toBeTruthy();
  await expectNoAxeViolations(dialog);
  fireEvent.click(existing);
  fireEvent.click(add);
  expect(api.POST).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Ladda fler (1/2)" }));
  const nextUser = await within(dialog).findByRole("radio", { name: "new@example.se" });
  expect(api.GET).toHaveBeenCalledWith(
    "/api/v1/users/",
    expect.objectContaining({
      params: { query: { email: undefined, limit: 100, cursor: "next-users" } }
    })
  );
  fireEvent.click(nextUser);
  fireEvent.click(add);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/spaces/{id}/members/", {
      params: { path: { id: "space-1" } },
      body: { id: "u4", role: "admin" }
    })
  );
});

it("searches users from the first character, once typing pauses", async () => {
  const { dialog } = await openDialog("Lägg till medlem");
  const search = within(dialog).getByLabelText("E-post");
  const searches = () =>
    api.GET.mock.calls
      .filter((call) => (call as unknown[])[0] === "/api/v1/users/")
      .map(
        (call) =>
          (call as { params: { query: { email?: string | null } } }[])[1]?.params.query.email
      )
      .filter(Boolean);

  vi.useFakeTimers();
  try {
    fireEvent.change(search, { target: { value: "a" } });
    act(() => vi.advanceTimersByTime(1000));
    expect(searches()).toEqual(["a"]);

    for (const value of ["an", "ann", "anna", "anna."]) {
      fireEvent.change(search, { target: { value } });
    }
    act(() => vi.advanceTimersByTime(1000));
    expect(searches()).toEqual(["a", "anna."]);
  } finally {
    vi.useRealTimers();
  }
});

it("resets the user cursor and cancels an unfinished next page when the search changes", async () => {
  let finish!: (value: { data: { items: unknown[] }; response: Response }) => void;
  let previousSignal: AbortSignal | undefined;
  api.GET.mockImplementation((_path, options) => {
    const request = options as {
      params: { query: { email?: string; cursor?: string } };
      signal: AbortSignal;
    };
    if (request.params.query.cursor) {
      previousSignal = request.signal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    }
    return Promise.resolve({
      data: {
        items: [
          {
            id: "candidate",
            email: request.params.query.email ? "bea@example.se" : "anna@example.se"
          }
        ],
        total_count: request.params.query.email ? 1 : 2,
        next_cursor: request.params.query.email ? null : "next"
      },
      response: new Response("{}")
    });
  });
  const { dialog } = await openDialog("Lägg till medlem");
  await within(dialog).findByRole("radio", { name: "anna@example.se" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Ladda fler (1/2)" }));
  await waitFor(() => expect(previousSignal).toBeDefined());
  fireEvent.change(within(dialog).getByLabelText("E-post"), { target: { value: "b" } });
  expect(await within(dialog).findByRole("radio", { name: "bea@example.se" })).toBeTruthy();
  expect(previousSignal?.aborted).toBe(true);
  expect(api.GET).toHaveBeenLastCalledWith(
    "/api/v1/users/",
    expect.objectContaining({
      params: { query: { email: "b", limit: 100, cursor: undefined } }
    })
  );
  await act(async () =>
    finish({
      data: { items: [{ id: "late", email: "late@example.se" }] },
      response: new Response("{}")
    })
  );
  expect(within(dialog).queryByRole("radio", { name: "late@example.se" })).toBeNull();
  expect(within(dialog).queryByRole("radio", { name: "anna@example.se" })).toBeNull();
});

it("searches the group picker and adds the chosen group with its role", async () => {
  api.GET.mockResolvedValue({
    data: {
      items: [
        { id: "g1", name: "HR" },
        { id: "g2", name: "Miljöenheten" }
      ]
    },
    response: new Response("{}")
  });
  const { dialog, add } = await openDialog("Lägg till grupp");
  fireEvent.click(within(dialog).getByRole("button", { name: "Användargrupper" }));
  const search = await screen.findByPlaceholderText("Välj en användargrupp...");
  fireEvent.change(search, { target: { value: "miljö" } });
  expect(screen.queryByRole("option", { name: "HR" })).toBeNull();
  fireEvent.click(await screen.findByRole("option", { name: "Miljöenheten" }));
  expect(
    within(dialog).getByRole("button", { name: /Användargrupper.*Miljöenheten/ })
  ).toBeTruthy();
  fireEvent.click(add);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/spaces/{id}/group-members/", {
      params: { path: { id: "space-1" } },
      body: { id: "g2", role: "admin" }
    })
  );
});

it("says a group must be picked when adding a group, at its picker", async () => {
  const { dialog, add } = await openDialog("Lägg till grupp");

  fireEvent.click(add);

  const group = within(dialog).getByRole("button", { name: "Användargrupper" });
  expect(group.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(group);
  expect(api.POST).not.toHaveBeenCalled();
});

/*
 * Decision 25, the artifact's members board: on a phone members are rows
 * (name, e-mail, role in words); a tap opens a sheet with the roles and
 * "Ta bort från ytan". No inline role selects.
 */
describe("members on a phone", () => {
  beforeEach(() => {
    setViewport("phone");
    state.space = spaceWithMembers();
  });

  it("lists members as rows by role, each with its role in words", async () => {
    const { container } = renderInApp(<SpaceMembers />);

    expect(screen.queryByRole("combobox", { name: "Roll" })).toBeNull();
    const editors = screen.getByRole("list", { name: /^Administratörer och redigerare/ });
    const self = within(editors)
      .getByText(/anna\.lind@example\.com \(du\)/)
      .closest("li")!;
    // Nobody changes their own role: no button, the role in words.
    expect(within(self).queryByRole("button")).toBeNull();
    expect(within(self).getByText("Administratör")).toBeTruthy();
    // A supporting fact at the e-mail's size; under the name below 20rem of the
    // rows (a 320 px phone), so the e-mail does not break mid-address.
    expect(within(self).getByText("Administratör").className).toBe(
      "hidden text-sm @min-[20rem]/rows:inline"
    );
    expect(within(self).getByText("Roll: Administratör").className).toBe(
      "block @min-[20rem]/rows:sr-only"
    );
    const erik = within(editors).getByRole("button", { name: /^erik\.johansson@example\.com/ });
    expect(erik.closest("li")!.textContent).toContain("Redigerare");

    const viewers = screen.getByRole("list", { name: /^Visare/ });
    // A username names the row; the e-mail is under it.
    expect(
      within(viewers).getByRole("button", { name: /^sofia sofia\.n@example\.com/ })
    ).toBeTruthy();
    const groups = screen.getByRole("list", { name: /^Gruppmedlemmar/ });
    const group = within(groups).getByRole("button", { name: /^Bygglovsenheten 12 användare/ });
    expect(group.closest("li")!.textContent).toContain("Visare");
    await expectNoAxeViolations(container);
  });

  it("changes a member's role from the sheet as soon as a role is picked", async () => {
    renderInApp(<SpaceMembers />);
    fireEvent.click(screen.getByRole("button", { name: /^erik\.johansson@example\.com/ }));

    const sheet = await screen.findByRole("dialog", { name: "erik.johansson@example.com" });
    // Buttons, not radios: moving through radios with the arrow keys would
    // pick each role on the way (WCAG 3.2.2).
    const roles = within(sheet).getByRole("list", { name: "Roll" });
    expect(within(sheet).queryByRole("radio")).toBeNull();
    expect(
      within(roles).getByRole("button", { name: /^Redigerare\s*, nuvarande roll/ })
    ).toBeTruthy();
    await expectNoAxeViolations(sheet);
    fireEvent.click(within(roles).getByRole("button", { name: /^Visare/ }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/members/{user_id}/", {
        params: { path: { id: "space-1", user_id: "u2" } },
        body: { role: "viewer" }
      })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("lets one pick save before another", async () => {
    let finish = () => {};
    api.PATCH.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => resolve({ data: {}, response: new Response("{}") });
        })
    );
    renderInApp(<SpaceMembers />);
    fireEvent.click(screen.getByRole("button", { name: /^erik\.johansson@example\.com/ }));
    const sheet = await screen.findByRole("dialog", { name: "erik.johansson@example.com" });
    const roles = within(sheet).getByRole("list", { name: "Roll" });

    fireEvent.click(within(roles).getByRole("button", { name: /^Visare/ }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    // The pick shows at once; another waits for it.
    expect(within(roles).getByRole("button", { name: /^Visare\s*, nuvarande roll/ })).toBeTruthy();
    fireEvent.click(within(roles).getByRole("button", { name: /^Administratör/ }));
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the confirmation open when a removal fails", async () => {
    api.DELETE.mockImplementation(() =>
      Promise.resolve({
        data: undefined,
        error: { detail: "nope" },
        response: new Response("{}", { status: 500 })
      })
    );
    renderInApp(<SpaceMembers />);
    fireEvent.click(screen.getByRole("button", { name: /^erik\.johansson@example\.com/ }));
    const sheet = await screen.findByRole("dialog", { name: "erik.johansson@example.com" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Ta bort från ytan" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Ta bort medlem" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(api.DELETE).toHaveBeenCalled());
    // No unhandled rejection (vitest fails the run on one); the dialog waits.
    expect(await screen.findByRole("alertdialog", { name: "Ta bort medlem" })).toBeTruthy();
  });

  it("removes a member from the space after a confirmation", async () => {
    renderInApp(<SpaceMembers />);
    fireEvent.click(screen.getByRole("button", { name: /^erik\.johansson@example\.com/ }));
    const sheet = await screen.findByRole("dialog", { name: "erik.johansson@example.com" });

    fireEvent.click(within(sheet).getByRole("button", { name: "Ta bort från ytan" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Ta bort medlem" });
    expect(confirm.textContent).toContain("erik.johansson@example.com");
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/spaces/{id}/members/{user_id}/", {
        params: { path: { id: "space-1", user_id: "u2" } }
      })
    );
  });

  it("opens the same sheet for a group", async () => {
    renderInApp(<SpaceMembers />);
    fireEvent.click(screen.getByRole("button", { name: /^Bygglovsenheten/ }));

    const sheet = await screen.findByRole("dialog", { name: "Bygglovsenheten" });
    expect(within(sheet).getByText("12 användare")).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: /^Redigerare/ }));
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/spaces/{id}/group-members/{group_id}/", {
        params: { path: { id: "space-1", group_id: "g1" } },
        body: { role: "editor" }
      })
    );
  });

  it("docks adding a member and a group at the bottom", () => {
    renderInApp(<SpaceMembers />);
    const dock = screen.getByRole("group", { name: "Medlemmar, åtgärder" });
    expect(within(dock).getByRole("button", { name: "Lägg till grupp" })).toBeTruthy();
    expect(within(dock).getByRole("button", { name: "Lägg till medlem" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Lägg till medlem" })).toHaveLength(1);
  });

  it("offers no changes to someone who may only read", () => {
    state.space = spaceWithMembers(["read"]);
    renderInApp(<SpaceMembers />);
    expect(screen.queryByRole("button", { name: /^erik\.johansson@example\.com/ })).toBeNull();
    expect(screen.getAllByText("Redigerare").length).toBeGreaterThan(0);
    expect(screen.queryByRole("group", { name: "Medlemmar, åtgärder" })).toBeNull();
  });
});

describe("members on a tablet", () => {
  it("names every role in words, not the API's English", () => {
    setViewport("tablet-portrait");
    state.space = spaceWithMembers();
    renderInApp(<SpaceMembers />);
    // The signed-in admin's own row is read-only.
    expect(screen.getByText("Administratör")).toBeTruthy();
    expect(screen.queryByText(/^admin$/i)).toBeNull();
    const roles = screen
      .getAllByRole("combobox", { name: "Roll" })
      .map((select) => select.textContent);
    expect(roles).toEqual(["Redigerare", "Visare", "Visare"]);
  });
});

describe("members across 768 px (a phone turned)", () => {
  const title = () => screen.getByRole("heading", { name: "Medlemmar" });

  it("moves focus from a member control that went with its layout to the title, both ways", async () => {
    state.space = spaceWithMembers();
    setViewport("phone");
    renderInApp(<SpaceMembers />);

    const row = screen.getByRole("button", { name: /^erik\.johansson@example\.com/ });
    act(() => row.focus());
    expect(document.activeElement).toBe(row);
    act(() => setViewport("tablet-portrait"));
    await waitFor(() => expect(document.activeElement).toBe(title()));
    expect(screen.queryByRole("button", { name: /^erik\.johansson@example\.com/ })).toBeNull();

    const role = screen.getAllByRole("combobox", { name: "Roll" })[0]!;
    act(() => role.focus());
    expect(document.activeElement).toBe(role);
    act(() => setViewport("phone"));
    await waitFor(() => expect(document.activeElement).toBe(title()));
    expect(screen.queryByRole("combobox", { name: "Roll" })).toBeNull();
  });

  it("leaves focus alone when it was on a control that stays", async () => {
    state.space = spaceWithMembers();
    setViewport("phone");
    renderInApp(<SpaceMembers />);

    // The add buttons are one element in both layouts (DockedActions).
    const add = screen.getAllByRole("button", { name: "Lägg till medlem" })[0]!;
    act(() => add.focus());
    act(() => setViewport("tablet-portrait"));
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(document.activeElement).toBe(add);
  });
});
