// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { WebsiteContent } from "./website-content";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  api.GET.mockReset();
});

const reply = (data: unknown) => ({ data, response: new Response("{}") });
const item = (id: string) => ({
  id,
  metadata: { title: `${id}.html`, size: 20, embedding_model_id: "model" },
  original_available: false
});
const page = (ids: string[], next_cursor: string | null = null) => ({
  items: ids.map(item),
  total_count: 2,
  next_cursor
});
type Options = { params: { query: { q?: string; cursor?: string } }; signal: AbortSignal };

function show(query = "") {
  return renderInApp(
    <>
      <h1 id="content">Innehåll</h1>
      <WebsiteContent websiteId="site" labelledBy="content" total={2} />
    </>,
    {
      route: `/spaces/space/knowledge/websites/site?tab=blobs&q=${query}`
    }
  );
}

it("cancels an old search and never replaces newer results with its late response", async () => {
  let finish!: (response: unknown) => void;
  let oldSignal: AbortSignal | undefined;
  api.GET.mockImplementation((path: string, options: Options) => {
    if (path.endsWith("content-folders/"))
      return Promise.resolve(reply({ items: [], next_cursor: null }));
    if (options.params.query.q === "old") {
      oldSignal = options.signal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    }
    return Promise.resolve(reply(page(["new"])));
  });
  show("old");
  await waitFor(() => expect(oldSignal).toBeDefined());
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new" } });
  expect(await screen.findByRole("button", { name: "new.html" })).toBeTruthy();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => finish(reply(page(["old"]))));
  expect(screen.queryByRole("button", { name: "old.html" })).toBeNull();
  expect(screen.getByRole("searchbox").getAttribute("value")).toBe("new");
});

it("keeps loaded content when the next page fails and retries that cursor", async () => {
  let failMore = true;
  const cursors: (string | undefined)[] = [];
  api.GET.mockImplementation((path: string, options: Options) => {
    if (path.endsWith("content-folders/"))
      return Promise.resolve(reply({ items: [], next_cursor: null }));
    const cursor = options.params.query.cursor;
    cursors.push(cursor);
    if (cursor && failMore)
      return Promise.resolve({
        error: { message: "Unavailable" },
        response: new Response("", { status: 503 })
      });
    return Promise.resolve(reply(cursor ? page(["second"]) : page(["first"], "more")));
  });
  show();
  expect(await screen.findByRole("button", { name: "first.html" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Läs in fler|Visa fler|Ladda fler/ }));
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  expect(screen.getByRole("button", { name: "first.html" })).toBeTruthy();
  failMore = false;
  fireEvent.click(retry);
  expect(await screen.findByRole("button", { name: "second.html" })).toBeTruthy();
  expect(cursors).toEqual([undefined, "more", "more"]);
});
