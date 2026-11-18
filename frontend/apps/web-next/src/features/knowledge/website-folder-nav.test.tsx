// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { WebsiteFolderNav } from "./website-folder-nav";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.GET.mockReset();
});

const origin = "https://example.test/";
const folder = (path: string, has_children = false) => ({ path, has_children, count: 3 });
const reply = (items: ReturnType<typeof folder>[], next_cursor: string | null = null) => ({
  data: { items, next_cursor },
  response: new Response("{}")
});
type Options = { params: { query: { prefix: string; cursor?: string } }; signal: AbortSignal };

function show(selectedPrefix = "") {
  return renderInApp(
    <WebsiteFolderNav
      websiteId="site"
      selectedPrefix={selectedPrefix}
      total={10}
      hrefFor={(prefix) => `?prefix=${encodeURIComponent(prefix)}`}
      onSelect={vi.fn()}
    />
  );
}

it("opens only the selected ancestry and cancels a collapsed branch read", async () => {
  const calls: string[] = [];
  let pendingSignal: AbortSignal | undefined;
  api.GET.mockImplementation((_path: string, { params, signal }: Options) => {
    const { prefix } = params.query;
    calls.push(prefix);
    if (!prefix) return Promise.resolve(reply([folder(origin, true)]));
    if (prefix === origin)
      return Promise.resolve(
        reply([folder(`${origin}docs/`, true), folder(`${origin}unrelated/`, true)])
      );
    if (prefix === `${origin}docs/`)
      return Promise.resolve(reply([folder(`${origin}docs/api/`, true)]));
    pendingSignal = signal;
    return new Promise(() => {});
  });
  show(`${origin}docs/api/`);
  const selected = await screen.findByRole("link", { name: /api/ });
  expect(selected.getAttribute("aria-current")).toBe("page");
  expect(calls).toEqual(["", origin, `${origin}docs/`]);
  fireEvent.click(screen.getByRole("button", { name: /Fäll ut api/ }));
  await waitFor(() => expect(pendingSignal).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: /Fäll ihop api/ }));
  await waitFor(() => expect(pendingSignal?.aborted).toBe(true));
  expect(calls).not.toContain(`${origin}unrelated/`);
});

it("keeps folder links on a paging failure and retries the failed cursor without duplicates", async () => {
  let fail = true;
  const cursors: (string | undefined)[] = [];
  api.GET.mockImplementation((_path: string, { params }: Options) => {
    const { cursor } = params.query;
    cursors.push(cursor);
    if (cursor && fail)
      return Promise.resolve({
        error: { message: "Unavailable" },
        response: new Response("", { status: 503 })
      });
    return Promise.resolve(
      cursor
        ? reply([folder(origin), folder("https://other.test/")])
        : reply([folder(origin)], "next")
    );
  });
  show();
  const nav = within(screen.getByRole("navigation"));
  expect(await nav.findByRole("link", { name: /example.test/ })).toBeTruthy();
  fireEvent.click(nav.getByRole("button", { name: /Visa fler mappar/ }));
  const retry = await nav.findByRole("button", { name: /Försök igen/ });
  expect(nav.getByRole("link", { name: /example.test/ })).toBeTruthy();
  fail = false;
  fireEvent.click(retry);
  expect(await nav.findByRole("link", { name: /other.test/ })).toBeTruthy();
  expect(nav.getAllByRole("link", { name: /example.test/ })).toHaveLength(1);
  expect(cursors).toEqual([undefined, "next", "next"]);
});
