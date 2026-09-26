// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Suspense, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShellContext } from "@/components/shell/shell-context";
import { CreateSpaceDialog } from "@/features/spaces/create-space-dialog";
import { expectNoAxeViolations } from "@/test/axe";
import { noopShell, renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({
  spaces: [] as unknown[],
  deleted: [] as string[],
  created: [] as unknown[]
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, prefetch: () => {} })
}));
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
      return Promise.resolve({ data: null, response: new Response(null, { status: 204 }) });
    }
  }
}));

import { SpacesList } from "./spaces-list.client";

afterEach(() => {
  cleanup();
  api.deleted.length = 0;
  api.created.length = 0;
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
  it("lists shared spaces as cards with counts, a filter and one create button", async () => {
    api.spaces = [
      space({}),
      space({ id: "s2", name: "HR", description: null, permissions: ["read"], applications: null }),
      space({ id: "personal", name: "Min yta", personal: true }),
      space({ id: "org", name: "Organisation", organization: true })
    ];
    const { container } = await show();

    expect(screen.getAllByRole("button", { name: "Skapa yta" })).toHaveLength(1);
    const list = screen.getAllByRole("list")[0]!;
    const cards = Array.from(list.children) as HTMLElement[];
    expect(
      cards.map((card) => within(card).getAllByRole("link")[0]!.getAttribute("aria-label"))
    ).toEqual(["HR", "Upphandling"]);
    expect(within(cards[0]!).getByText("Ingen beskrivning")).toBeTruthy();
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

  it("announces how many spaces match the filter", async () => {
    api.spaces = [space({}), space({ id: "s2", name: "HR" })];
    await show();
    const status = () => document.querySelector("[data-astryx-live-region='polite']");

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera ytor" }), {
      target: { value: "hr" }
    });
    await waitFor(() => expect(status()?.textContent).toBe("1 träff"));
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera ytor" }), {
      target: { value: "saknas" }
    });
    await waitFor(() => expect(status()?.textContent).toBe("Inga träffar"));
  });

  it("deletes a space from its more-menu only after the name is typed", async () => {
    api.spaces = [space({})];
    await show();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Upphandling" }));
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
