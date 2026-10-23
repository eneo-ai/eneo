// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { CrawlRunDetailsDialog } from "./crawl-run-details";
import type { CrawlRun } from "./knowledge";

const RUN: CrawlRun = {
  id: "run-1",
  status: "complete",
  phase: "terminal",
  outcome: "partial",
  origin: "manual",
  pages_crawled: 40,
  pages_unchanged: 5,
  files_downloaded: 0,
  files_unchanged: 0,
  pages_failed: 3,
  files_failed: 1,
  failure_summary: { http_404: 3, file_too_large: 1 },
  failure_code: "processing_failed",
  failure_detail: null,
  result_location: null,
  created_at: "2026-09-25T08:00:00Z",
  finished_at: "2026-09-25T08:10:00Z",
  cancel_requested_at: null,
  attempt_count: 1
};

const failure = (id: string, kind: "page" | "file", reason = "http_404") => ({
  id,
  kind,
  reason,
  url: `https://example.com/${id}`
});

const state = vi.hoisted(() => ({
  requests: [] as Record<string, unknown>[],
  failWith: null as string | null
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (_path: string, options: { params: { query: Record<string, unknown> } }) => {
      const query = options.params.query;
      state.requests.push(query);
      if (state.failWith) {
        const error = state.failWith;
        state.failWith = null;
        return Promise.resolve({
          error: { message: error },
          response: new Response(null, { status: 500 })
        });
      }
      const kind = query.kind as "page" | "file" | null;
      const pages = [failure("a", "page"), failure("b", "page"), failure("c", "page")];
      const files = [failure("d", "file", "file_too_large")];
      const all = kind === "page" ? pages : kind === "file" ? files : [...pages, ...files];
      const cursor = query.cursor as string | null;
      const items = cursor ? all.slice(2) : all.slice(0, 2);
      return Promise.resolve({
        data: {
          items,
          total_count: all.length,
          next_cursor: !cursor && all.length > 2 ? "more" : null,
          details_available: true,
          run: RUN
        },
        response: new Response("{}")
      });
    }
  }
}));

afterEach(() => {
  cleanup();
  state.requests = [];
  state.failWith = null;
});

function show(initialKind: "page" | "file" | null = null) {
  const onOpenChange = vi.fn();
  const onRerun = vi.fn();
  const view = renderInApp(
    <CrawlRunDetailsDialog
      run={RUN}
      isOpen
      onOpenChange={onOpenChange}
      initialKind={initialKind}
      onRerun={onRerun}
    />
  );
  return { ...view, onOpenChange, onRerun };
}

describe("CrawlRunDetailsDialog", () => {
  it("shows the run's counts and loads its failed addresses a page at a time", async () => {
    const { container } = show();
    const dialog = await screen.findByRole("dialog", { name: /^Indexering / });
    expect(within(dialog).getByText("Startad manuellt")).toBeTruthy();
    const counts = within(dialog).getByRole("table", { name: "Resultat för denna körning" });
    expect(
      within(counts).getByRole("button", { name: "Visa sidor som inte kunde indexeras (3)" })
    ).toBeTruthy();

    const list = await within(dialog).findByRole("list", { name: "Misslyckade adresser" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await expectNoAxeViolations(container);

    fireEvent.click(within(dialog).getByRole("button", { name: "Visa fler adresser (2/4)" }));
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(4));
    expect(state.requests.at(-1)).toMatchObject({ cursor: "more", kind: null });
    expect(within(dialog).queryByRole("button", { name: /Visa fler adresser/ })).toBeNull();
    expect(within(list).getByText("Innehållet var för stort")).toBeTruthy();
  });

  it("filters the addresses by kind from the segmented control and the counts", async () => {
    show("file");
    const dialog = await screen.findByRole("dialog");
    const group = within(dialog).getByRole("radiogroup", { name: "Typ" });
    expect(within(group).getByRole("radio", { name: "Filer" }).getAttribute("aria-checked")).toBe(
      "true"
    );
    await waitFor(() => expect(state.requests.at(-1)).toMatchObject({ kind: "file" }));
    const list = await within(dialog).findByRole("list", { name: "Misslyckade adresser" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);

    fireEvent.click(within(group).getByRole("radio", { name: "Alla" }));
    await waitFor(() => expect(state.requests.at(-1)).toMatchObject({ kind: null }));

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Visa sidor som inte kunde indexeras (3)" })
    );
    await waitFor(() => expect(state.requests.at(-1)).toMatchObject({ kind: "page" }));
    expect(within(group).getByRole("radio", { name: "Sidor" }).getAttribute("aria-checked")).toBe(
      "true"
    );
  });

  it("offers a retry when the addresses could not be loaded", async () => {
    state.failWith = "boom";
    show();
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("Kunde inte hämta misslyckade adresser. Försök igen.")
    ).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Försök igen" }));
    expect(await within(dialog).findByRole("list", { name: "Misslyckade adresser" })).toBeTruthy();
  });

  it("closes and hands over to the caller's rerun", async () => {
    const { onOpenChange, onRerun } = show();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Kör om hela webbplatsen" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onRerun).toHaveBeenCalledTimes(1);
  });
});
