// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { openMenuOnRelease, tap } from "@/test/menus";
import { renderInApp, testQueryClient } from "@/test/render";
import { PHONE_VIEWPORT, setViewport } from "@/test/setup-dom";

const backend = vi.hoisted(() => ({
  runs: [] as AppRunSparse[],
  deleted: [] as string[],
  refuseDelete: false,
  deleteGate: null as Promise<void> | null
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));
const run = (id: string, text: string | null, created_at: string): AppRunSparse => ({
  id,
  status: "complete",
  input: { text, files: [] },
  created_at,
  finished_at: null,
  user: { id: "user", email: "test@example.org" },
  skill_provenance: []
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: backend.runs }, response: new Response("{}") }),
    DELETE: async (path: string, { params }: { params: { path: { id: string } } }) => {
      if (backend.deleteGate) await backend.deleteGate;
      if (backend.refuseDelete)
        return Promise.resolve({
          error: { message: "Unavailable" },
          response: new Response("{}", { status: 503, headers: { "x-trace-id": "result-trace" } })
        });
      backend.deleted.push(`${path} ${params.path.id}`);
      backend.runs = backend.runs.filter((run) => run.id !== params.path.id);
      return Promise.resolve({ data: null, response: new Response(null, { status: 204 }) });
    }
  }
}));

import type { AppRunSparse } from "../apps";
import { ResultsTable } from "./results-table";

beforeEach(() => {
  backend.runs = [
    run("run-1", "Sammanfatta protokollet", "2026-09-20T08:00:00Z"),
    run("run-2", null, "2026-09-21T09:30:00Z")
  ];
  backend.deleted = [];
  backend.refuseDelete = false;
  backend.deleteGate = null;
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResultsTable", () => {
  it("takes its name from the app page's Resultat tab", async () => {
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/apps/app-1/results/${id}`} />);

    const table = await screen.findByRole("table", { name: "Resultat" });
    expect(within(table).getByText(/Sammanfatta protokollet/)).toBeTruthy();
    // The column of row menus has a header a screen reader can say (not an empty cell).
    expect(within(table).getAllByRole("columnheader").at(-1)?.textContent).toBe("Åtgärder");
  });

  it("names each run's menu by the time its row shows", async () => {
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/apps/app-1/results/${id}`} />);

    const rows = (await screen.findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      // A run has no name of its own: the menu says the time in the row's
      // Skapad cell, as the row writes it.
      const time = within(row).getAllByRole("cell")[2]!.textContent!;
      expect(time).toMatch(/2026/);
      expect(within(row).getByRole("button", { name: `Fler åtgärder för ${time}` })).toBeTruthy();
    }
  });

  it("is a list of rows on a phone, one per run, each opening its result", async () => {
    setViewport(PHONE_VIEWPORT);
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/apps/app-1/results/${id}`} />);

    const list = await screen.findByRole("list", { name: "Resultat" });
    expect(screen.queryByRole("table")).toBeNull();
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/apps/app-1/results/run-2",
      "/apps/app-1/results/run-1"
    ]);
    expect(within(list).getByText(/Sammanfatta protokollet/)).toBeTruthy();
    // Each row has its menu, named by the time the row shows.
    expect(within(list).getAllByRole("button", { name: /^Fler åtgärder för / })).toHaveLength(2);
  });
});

it("filters result titles and sorts name, status and created without mutating cached runs", async () => {
  const item = (
    id: string,
    text: string | null,
    status: AppRunSparse["status"],
    created_at: string
  ): AppRunSparse => ({
    id,
    input: { text, files: [] },
    status,
    created_at,
    finished_at: null,
    user: { id: "user", email: "test@example.org" },
    skill_provenance: []
  });
  const runs = [
    item("z", "Zeta", "queued", "2026-01-01T00:00:00Z"),
    item("a", "Alfa", "failed", "2026-01-03T00:00:00Z"),
    item("b", null, "complete", "2026-01-02T00:00:00Z")
  ];
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1", "runs"], runs);
  renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />, {
    queryClient
  });
  const table = await screen.findByRole("table", { name: "Resultat" });
  const order = () =>
    within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getByRole("link").getAttribute("href"));
  expect(order()).toEqual(["/results/a", "/results/b", "/results/z"]);
  const column = (name: string) =>
    within(table).getByRole("columnheader", { name: new RegExp(name) });
  fireEvent.click(within(column("Namn")).getByRole("button"));
  expect(order()).toEqual(["/results/b", "/results/a", "/results/z"]);
  expect(column("Namn").getAttribute("aria-sort")).toBe("ascending");
  fireEvent.click(within(column("Namn")).getByRole("button"));
  expect(order()).toEqual(["/results/z", "/results/a", "/results/b"]);
  fireEvent.click(within(column("Status")).getByRole("button"));
  // The Swedish visible statuses sort I kö, Misslyckades, Slutförd.
  expect(order()).toEqual(["/results/z", "/results/a", "/results/b"]);
  fireEvent.click(within(column("Skapad")).getByRole("button"));
  expect(order()).toEqual(["/results/z", "/results/b", "/results/a"]);
  const filter = screen.getByRole("textbox", { name: "Filtrera resultat" });
  fireEvent.change(filter, { target: { value: "alfa" } });
  expect(order()).toEqual(["/results/a"]);
  fireEvent.change(filter, { target: { value: "saknas" } });
  expect(screen.getByRole("heading", { name: "Inga resultat hittades" })).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "Filtrera resultat" })).toBe(filter);
  expect(runs.map((run) => run.id)).toEqual(["z", "a", "b"]);
});

it("filters by the visible empty-input title and uses it in the deletion confirmation", async () => {
  const emptyTitle = "Den här körningen tog inte emot några indata.";
  renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />);
  await screen.findByRole("table", { name: "Resultat" });
  expect(screen.getByRole("link", { name: emptyTitle })).toBeTruthy();

  fireEvent.change(screen.getByRole("textbox", { name: "Filtrera resultat" }), {
    target: { value: emptyTitle }
  });
  expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
    "/results/run-2"
  ]);
  const row = screen.getByRole("link", { name: emptyTitle }).closest("tr")!;
  const menu = await openMenuOnRelease(within(row).getByRole("button"));
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(
    within(dialog).getByText(`Vill du verkligen ta bort resultatet ${emptyTitle}?`)
  ).toBeTruthy();
});

/** Picks Ta bort from the menu of `button`, opened from the keyboard. */
async function chooseDelete(button: HTMLElement) {
  fireEvent.keyDown(button, { key: "Enter" });
  const menu = document.getElementById(button.getAttribute("aria-controls") ?? "")!;
  fireEvent.click(await within(menu).findByRole("menuitem", { name: "Ta bort" }));
}

async function requestDelete(id: string) {
  const table = await screen.findByRole("table", { name: "Resultat" });
  const row = within(table)
    .getAllByRole("row")
    .find((row) => row.querySelector(`a[href='/results/${id}']`))!;
  const menu = within(row).getByRole("button");
  menu.focus();
  await chooseDelete(menu);
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
  return dialog;
}

it.each([false, true])(
  "restores removal focus to a neighboring run or the stable empty list (last: %s)",
  async (last) => {
    if (last) backend.runs = [backend.runs[0]!];
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />);
    await requestDelete("run-1");
    await waitFor(() => expect(backend.deleted).toEqual(["/api/v1/app-runs/{id}/ run-1"]));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() =>
      expect(document.activeElement).toBe(
        last ? screen.getByRole("group", { name: "Resultat" }) : screen.getByRole("link")
      )
    );
  }
);

it("keeps a refused deletion open with its result and trace id, then permits retry", async () => {
  backend.refuseDelete = true;
  renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />);
  const dialog = await requestDelete("run-1");
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "Unavailable",
      expect.objectContaining({ description: expect.stringContaining("result-trace") })
    )
  );
  expect(screen.getByRole("alertdialog")).toBe(dialog);
  expect(backend.runs).toHaveLength(2);
  backend.refuseDelete = false;
  fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
});

it.each([false, true])(
  "keeps result deletion open across phone/tablet changes, including a pending request (refused: %s)",
  async (refused) => {
    setViewport(PHONE_VIEWPORT);
    backend.refuseDelete = refused;
    let finish!: () => void;
    backend.deleteGate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />);
    const list = await screen.findByRole("list", { name: "Resultat" });
    const menu = within(list)
      .getAllByRole("button", { name: /^Fler åtgärder för / })
      .at(-1)!;
    await chooseDelete(menu);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Sammanfatta protokollet/)).toBeTruthy();

    for (const viewport of ["tablet-portrait", "phone"] as const) {
      act(() => setViewport(viewport));
      expect(screen.getByRole("alertdialog")).toBe(dialog);
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Tar bort..." }).getAttribute("aria-busy")
      ).toBe("true")
    );
    for (const viewport of ["tablet-portrait", "phone"] as const) {
      act(() => setViewport(viewport));
      expect(screen.getByRole("alertdialog")).toBe(dialog);
      expect(
        within(dialog).getByRole("button", { name: "Tar bort..." }).getAttribute("aria-busy")
      ).toBe("true");
    }

    await act(async () => finish());
    if (refused) {
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Unavailable",
          expect.objectContaining({ description: expect.stringContaining("result-trace") })
        )
      );
      expect(screen.getByRole("alertdialog")).toBe(dialog);
      expect(backend.runs).toHaveLength(2);
      backend.refuseDelete = false;
      fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    }
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(backend.deleted).toEqual(["/api/v1/app-runs/{id}/ run-1"]);
  }
);

it("returns focus to the result list when cancellation follows a layout change", async () => {
  setViewport(PHONE_VIEWPORT);
  renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/results/${id}`} />);
  const list = await screen.findByRole("list", { name: "Resultat" });
  const focusTarget = screen.getByRole("group", { name: "Resultat" });
  const menu = within(list)
    .getAllByRole("button", { name: /^Fler åtgärder för / })
    .at(-1)!;
  // Tapped: jsdom does not make the page behind the dialog inert, so a menu
  // closed from the keyboard would refocus its button there as no browser does.
  const item = within(await openMenuOnRelease(menu)).getByRole("menuitem", { name: "Ta bort" });
  tap(item);
  const dialog = await screen.findByRole("alertdialog");
  act(() => setViewport("tablet-portrait"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(focusTarget));
  expect(backend.deleted).toEqual([]);
});
