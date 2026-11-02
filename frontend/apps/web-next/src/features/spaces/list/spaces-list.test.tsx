// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Suspense, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShellContext } from "@/components/shell/shell-context";
import { CreateSpaceDialog } from "@/features/spaces/create-space-dialog";
import { expectNoAxeViolations } from "@/test/axe";
import { noopShell, recordAnnouncements, renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { router } from "@/test/navigation";
import messages from "@/lib/i18n/messages/sv.json";

const api = vi.hoisted(() => ({
  spaces: [] as unknown[],
  deleted: [] as string[],
  created: [] as unknown[],
  deleteResult: null as Promise<unknown> | null
}));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: { items: api.spaces },
        response: new Response("{}", { status: 200 })
      }),
    POST: (_path: string, { body }: { body: unknown }) => {
      api.created.push(body);
      return Promise.resolve({
        data: { id: "new" },
        response: new Response("{}", { status: 200 })
      });
    },
    DELETE: (_path: string, { params }: { params: { path: { id: string } } }) => {
      api.deleted.push(params.path.id);
      return (
        api.deleteResult ??
        Promise.resolve({ data: null, response: new Response(null, { status: 204 }) })
      );
    }
  }
}));

import { SpacesList } from "@/features/spaces/list/spaces-list";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  api.deleted.length = 0;
  api.created.length = 0;
  api.deleteResult = null;
});

const count = (value: number) => ({ items: [], count: value, permissions: ["read"] });

const space = (overrides: Record<string, unknown>) => ({
  id: "s1",
  name: "Upphandling",
  description: "Stöd för upphandlare.",
  personal: false,
  organization: false,
  permissions: ["read", "delete"],
  applications: {
    assistants: count(2),
    group_chats: count(1),
    services: count(0),
    apps: count(1)
  },
  ...overrides
});

/** The app shell's part: it hosts the one create-space dialog. */
function Shell({ children }: { children: React.ReactNode }) {
  const [creating, setCreating] = useState(false);
  return (
    <ShellContext value={{ ...noopShell, openCreateSpace: () => setCreating(true) }}>
      {children}
      <CreateSpaceDialog open={creating} onOpenChange={setCreating} />
    </ShellContext>
  );
}

async function show() {
  const view = renderInApp(
    <Shell>
      <Suspense fallback={null}>
        <SpacesList title="Ytor" />
      </Suspense>
    </Shell>,
    { appContext: testAppContext({ permissions: ["shared_spaces"] }) }
  );
  await screen.findByRole("heading", { level: 1, name: "Ytor" });
  return view;
}

describe("SpacesList", () => {
  it("shows the five-second deletion hint and resets it after failure and retry settlement", async () => {
    let finish!: (value: unknown) => void;
    api.deleteResult = new Promise((resolve) => {
      finish = resolve;
    });
    api.spaces = [space({})];
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandling" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Radera yta" }));
    const dialog = await screen.findByRole("dialog", { name: "Radera yta" });
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "Ange ytnamnet för att bekräfta" }),
      { target: { value: "Upphandling" } }
    );
    vi.useFakeTimers();
    try {
      fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta borttagning" }));
      await act(async () => vi.advanceTimersByTimeAsync(4999));
      expect(within(dialog).queryByText(messages.delete_space_hint)).toBeNull();
      await act(async () => vi.advanceTimersByTimeAsync(1));
      expect(within(dialog).getByText(messages.delete_space_hint)).toBeTruthy();
      await act(async () => {
        finish({
          error: { message: "Fixture deletion refused" },
          response: new Response("{}", { status: 400 })
        });
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(within(dialog).queryByText(messages.delete_space_hint)).toBeNull();
      api.deleteResult = new Promise((resolve) => {
        finish = resolve;
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta borttagning" }));
      await act(async () => vi.advanceTimersByTimeAsync(4999));
      expect(within(dialog).queryByText(messages.delete_space_hint)).toBeNull();
      api.spaces = [];
      await act(async () => {
        finish({ data: null, response: new Response(null, { status: 204 }) });
        await vi.advanceTimersByTimeAsync(5001);
      });
      expect(screen.queryByText(messages.delete_space_hint)).toBeNull();
      expect(api.deleted).toEqual(["s1", "s1"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["list", "cards"])("offers Edit without delete permission in %s view", async (view) => {
    api.spaces = [space({ permissions: ["read", "edit"] })];
    await show();
    if (view === "cards") fireEvent.click(screen.getByRole("button", { name: "Kort" }));
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandling" }));
    const edit = await screen.findByRole("menuitem", { name: "Redigera" });
    expect(screen.queryByRole("menuitem", { name: "Radera yta" })).toBeNull();
    fireEvent.click(edit);
    expect(router.push).toHaveBeenCalledExactlyOnceWith("/spaces/s1/settings");
    expect(api.deleted).toEqual([]);
  });

  it("lists shared spaces as cards with counts, a filter and one create button", async () => {
    api.spaces = [
      space({}),
      space({ id: "s2", name: "HR", description: null, permissions: ["read"], applications: null }),
      space({ id: "personal", name: "Min yta", personal: true }),
      space({ id: "org", name: "Organisation", organization: true })
    ];
    const { container } = await show();
    fireEvent.click(screen.getByRole("button", { name: "Kort" }));

    expect(screen.getAllByRole("button", { name: "Skapa yta" })).toHaveLength(1);
    const list = screen.getAllByRole("list")[0]!;
    const cards = Array.from(list.children) as HTMLElement[];
    expect(
      cards.map((card) => within(card).getAllByRole("link")[0]!.getAttribute("aria-label"))
    ).toEqual(["HR", "Upphandling"]);
    // No description, no placeholder line (as assistants and apps).
    expect(within(cards[0]!).queryByText("Ingen beskrivning")).toBeNull();
    expect(within(cards[0]!).queryByRole("button")).toBeNull();
    expect(within(cards[1]!).getByText("3 assistenter")).toBeTruthy();
    expect(within(cards[1]!).getByText("1 app")).toBeTruthy();
    expect(within(cards[1]!).getByRole("link", { name: "Upphandling" }).getAttribute("href")).toBe(
      "/spaces/s1/overview"
    );

    await expectNoAxeViolations(container);

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera ytor" }), {
      target: { value: "hr" }
    });
    expect(screen.getByRole("link", { name: "HR" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Upphandling" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera ytor" }), {
      target: { value: "saknas" }
    });
    expect(screen.getByRole("heading", { name: "Inga resultat hittades" })).toBeTruthy();
  });

  it("announces how many spaces match the filter, once for each query", async () => {
    api.spaces = [space({}), space({ id: "s2", name: "HR" })];
    await show();
    const said = recordAnnouncements();
    const status = () => document.querySelector("[data-astryx-live-region='polite']");
    const filter = (value: string) =>
      fireEvent.change(screen.getByRole("textbox", { name: "Filtrera ytor" }), {
        target: { value }
      });

    filter("hr");
    await waitFor(() => expect(said).toEqual(["1 träff"]));
    // The count owns the empty result: its empty state does not say it again.
    filter("saknas");
    await waitFor(() => expect(said).toEqual(["1 träff", "Inga träffar"]));
    expect(screen.getByRole("heading", { name: "Inga resultat hittades" })).toBeTruthy();
    filter("saknas ännu");
    await waitFor(() => expect(said).toEqual(["1 träff", "Inga träffar", "Inga träffar"]));
    filter("");
    await waitFor(() => expect(status()?.textContent).toBe(""));
    await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));
    expect(said).toEqual(["1 träff", "Inga träffar", "Inga träffar"]);
  });

  it("deletes a space from its more-menu only after the name is typed", async () => {
    api.spaces = [space({})];
    await show();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandling" }));
    expect(screen.queryByRole("menuitem", { name: "Redigera" })).toBeNull();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Radera yta" }));

    const dialog = await screen.findByRole("dialog", { name: "Radera yta" });
    const confirm = within(dialog).getByRole("button", { name: "Bekräfta borttagning" });
    const field = within(dialog).getByRole("textbox", { name: "Ange ytnamnet för att bekräfta" });
    // Never disabled: deleting without the name says so at the field, which takes focus.
    expect(confirm.hasAttribute("disabled")).toBe(false);
    fireEvent.change(field, { target: { value: "Upphand" } });
    fireEvent.click(confirm);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(
      within(dialog).getByText("Det stämmer inte. Skriv Upphandling exakt som det står.")
    ).toBeTruthy();
    expect(document.activeElement).toBe(field);
    expect(api.deleted).toEqual([]);
    await expectNoAxeViolations(dialog);

    fireEvent.change(field, { target: { value: "Upphandling" } });
    api.spaces = [];
    fireEvent.click(confirm);
    await waitFor(() => expect(api.deleted).toEqual(["s1"]));
    // The card and its menu button are gone: focus goes to the page heading.
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Radera yta" })).toBeNull());
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Ytor" }))
    );
  });

  it("closes the delete dialog with Escape without deleting", async () => {
    api.spaces = [space({})];
    await show();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandling" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Radera yta" }));
    const dialog = await screen.findByRole("dialog", { name: "Radera yta" });

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Radera yta" })).toBeNull());
    expect(screen.queryByRole("textbox", { name: "Ange ytnamnet för att bekräfta" })).toBeNull();
    expect(api.deleted).toEqual([]);
  });

  it("puts the only create button in the empty state and keeps the Namn dialog", async () => {
    api.spaces = [];
    const { container } = await show();

    expect(screen.getByRole("heading", { name: "Inga ytor ännu" })).toBeTruthy();
    const create = screen.getAllByRole("button", { name: "Skapa yta" });
    expect(create).toHaveLength(1);
    await expectNoAxeViolations(container);

    // No name field exists until the dialog opens.
    expect(screen.queryByLabelText(/Namn/)).toBeNull();
    fireEvent.click(create[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny yta" });
    await expectNoAxeViolations(dialog);
    fireEvent.change(within(dialog).getByLabelText(/Namn/), { target: { value: " Ny yta " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa yta" }));
    await waitFor(() => expect(api.created).toEqual([{ name: "Ny yta" }]));
  });
});

describe("SpacesList on a phone (decision 9)", () => {
  it("lists the spaces as rows, each row one link with what it holds", async () => {
    setViewport("phone");
    api.spaces = [
      space({}),
      space({ id: "s2", name: "HR", description: null, permissions: ["read"], applications: null })
    ];
    const { container } = await show();
    const rows = within(screen.getAllByRole("list")[0]!).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const upphandling = within(rows[1]!).getByRole("link", { name: /^Upphandling/ });
    expect(upphandling.getAttribute("href")).toBe("/spaces/s1/overview");
    expect(upphandling.textContent).toContain("3 assistenter · 1 app");
    expect(within(rows[0]!).getByRole("link", { name: /^HR/ }).textContent).not.toContain(
      "Ingen beskrivning"
    );
    expect(
      within(rows[1]!).getByRole("button", { name: "Fler åtgärder för Upphandling" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});

it("opens spaces as a name-sortable list, switches to cards and remembers that view", async () => {
  api.spaces = [space({}), space({ id: "s2", name: "HR", permissions: ["read"] })];
  await show();
  const table = screen.getByRole("table", { name: "Ytor" });
  expect(within(table).queryByRole("columnheader", { name: /Status/ })).toBeNull();
  const links = () =>
    within(table)
      .getAllByRole("link")
      .map((link) => link.textContent);
  expect(links()).toEqual(["HR", "Upphandling"]);
  fireEvent.click(
    within(within(table).getByRole("columnheader", { name: /Namn/ })).getByRole("button")
  );
  expect(links()).toEqual(["Upphandling", "HR"]);
  const readOnly = within(table)
    .getAllByRole("row")
    .find((row) => row.textContent?.includes("HR"))!;
  expect(within(readOnly).queryByRole("button")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Kort" }));
  expect(screen.queryByRole("table")).toBeNull();
  cleanup();
  await show();
  expect(screen.getByRole("button", { name: "Kort" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("table")).toBeNull();
});
