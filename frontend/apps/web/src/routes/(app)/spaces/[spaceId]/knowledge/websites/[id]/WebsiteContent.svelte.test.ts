import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, test, vi } from "vitest";
import type { WebsiteInfoBlobPage } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import "../../../../../../../app.css";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  folders: vi.fn(),
  route: { url: new URL("http://localhost/?tab=blobs"), state: {} }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ websites: { indexedBlobs: { listPage: api.list, folders: api.folders } } })
}));
vi.mock("$app/state", () => ({ page: api.route }));
vi.mock("$app/navigation", () => ({
  replaceState: (url: string, state: object) => {
    api.route.url = new URL(url, api.route.url);
    api.route.state = state;
  }
}));
import WebsiteContent from "./WebsiteContent.svelte";

const origin = "https://example.test/";
// The visible count is paired with a spoken unit, so the link name carries both.
const folderName = (name: string, count: number) =>
  new RegExp(`^${name} ?, ${m.website_source_resource_count({ count })}$`);
const content = (name: string, path = ""): WebsiteInfoBlobPage["items"][number] => ({
  id: name,
  metadata: { title: name, url: `${origin}${path}${name}`, size: 100, embedding_model_id: "model" },
  original_available: false,
  created_at: "2026-10-19T09:00:00Z"
});
function result(
  items = [content("First document")],
  next: string | null = null
): WebsiteInfoBlobPage {
  return {
    items,
    count: items.length,
    total_count: next ? 120 : items.length,
    next_cursor: next,
    limit: 100
  };
}

beforeEach(() => {
  api.route.url = new URL("http://localhost/?tab=blobs");
  api.route.state = {};
  api.list.mockReset().mockResolvedValue(result());
  api.folders.mockReset().mockImplementation(async ({ prefix }: { prefix: string }) => ({
    items: prefix
      ? [
          { path: `${origin}A/`, count: 40, has_children: false },
          { path: `${origin}B/`, count: 80, has_children: false }
        ]
      : [{ path: origin, count: 120, has_children: true }],
    next_cursor: null
  }));
});

test("searches the entire index and keeps filters in the URL", async () => {
  render(WebsiteContent, { websiteId: "website", initialPage: result() });
  api.list.mockResolvedValue(result([content("Previously unloaded document")]));
  await page.getByRole("searchbox").fill("unloaded");
  await expect
    .element(page.getByRole("button", { name: "Previously unloaded document" }))
    .toBeVisible();
  expect(api.list).toHaveBeenLastCalledWith({
    id: "website",
    limit: 100,
    cursor: null,
    q: "unloaded"
  });
  expect(api.route.url.searchParams.get("q")).toBe("unloaded");
  await expectNoAxeViolations(document.body);
});

test("a late folder response cannot replace the currently selected folder", async () => {
  let resolveFirst: (value: WebsiteInfoBlobPage) => void = () => {};
  render(WebsiteContent, { websiteId: "website", initialPage: result() });
  api.list.mockImplementationOnce(
    () =>
      new Promise<WebsiteInfoBlobPage>((resolve) => {
        resolveFirst = resolve;
      })
  );
  await page.getByRole("link", { name: folderName("A", 40) }).click();
  api.list.mockResolvedValueOnce(result([content("Document B", "B/")]));
  await page.getByRole("link", { name: folderName("B", 80) }).click();
  await expect.element(page.getByRole("button", { name: "Document B" })).toBeVisible();
  resolveFirst(result([content("Document A", "A/")]));
  await expect.element(page.getByRole("button", { name: "Document A" })).not.toBeInTheDocument();
  expect(api.route.url.searchParams.get("prefix")).toBe(`${origin}B/`);
  await expect
    .element(page.getByRole("link", { name: folderName("B", 80) }))
    .toHaveAttribute("aria-current", "page");
});

test("failed pagination retains content and retries the same cursor", async () => {
  render(WebsiteContent, { websiteId: "website", initialPage: result(undefined, "first-page") });
  api.list.mockRejectedValueOnce(new Error("offline"));
  await page
    .getByRole("button", { name: m.website_indexed_content_load_more({ current: 1, total: 120 }) })
    .click();
  await expect.element(page.getByRole("alert")).toBeVisible();
  await expect.element(page.getByRole("button", { name: "First document" })).toBeVisible();
  api.list.mockResolvedValueOnce(result([content("Next document")]));
  await page.getByRole("button", { name: m.retry() }).click();
  await expect.element(page.getByRole("button", { name: "Next document" })).toBeVisible();
  await expect.element(page.getByRole("button", { name: "First document" })).toBeVisible();
  expect(api.list).toHaveBeenLastCalledWith({ id: "website", limit: 100, cursor: "first-page" });
});

test("folder failures are visible and retryable without blocking indexed content", async () => {
  api.folders.mockRejectedValueOnce(new Error("offline"));
  render(WebsiteContent, { websiteId: "website", initialPage: result() });
  await expect.element(page.getByRole("button", { name: "First document" })).toBeVisible();
  await page.getByRole("button", { name: m.source_tree_retry() }).click();
  await expect.element(page.getByRole("link", { name: folderName("A", 40) })).toBeVisible();
});

test("a deep link loads its selected prefix and query without loading every document", async () => {
  api.route.url = new URL(
    `http://localhost/?tab=blobs&prefix=${encodeURIComponent(origin + "A/")}&q=pdf`
  );
  api.list.mockResolvedValue(result([content("guide.pdf", "A/")]));
  render(WebsiteContent, { websiteId: "website", initialPage: result() });
  await expect.element(page.getByRole("button", { name: "guide.pdf" })).toBeVisible();
  expect(api.list).toHaveBeenCalledExactlyOnceWith({
    id: "website",
    limit: 100,
    cursor: null,
    prefix: origin + "A/",
    q: "pdf"
  });
  await expect.element(page.getByRole("searchbox")).toHaveValue("pdf");
});

test("directory pagination stays in its branch and nested folders load on expansion", async () => {
  api.folders.mockImplementation(
    async ({ prefix, cursor }: { prefix: string; cursor?: string }) => {
      if (!prefix)
        return { items: [{ path: origin, count: 120, has_children: true }], next_cursor: null };
      if (prefix === origin && !cursor)
        return {
          items: [{ path: origin + "A/", count: 40, has_children: true }],
          next_cursor: "first"
        };
      if (prefix === origin)
        return {
          items: [{ path: origin + "B/", count: 80, has_children: false }],
          next_cursor: null
        };
      return {
        items: [{ path: origin + "A/nested/", count: 20, has_children: false }],
        next_cursor: null
      };
    }
  );
  render(WebsiteContent, { websiteId: "website", initialPage: result() });
  await page.getByRole("button", { name: m.source_tree_more() }).click();
  await expect.element(page.getByRole("link", { name: folderName("B", 80) })).toBeVisible();
  expect(api.folders).not.toHaveBeenCalledWith(expect.objectContaining({ prefix: origin + "A/" }));
  await page
    .getByRole("button", { name: m.source_tree_expand({ name: "A" }), exact: true })
    .click();
  await expect.element(page.getByRole("link", { name: folderName("nested", 20) })).toBeVisible();
  await page
    .getByRole("button", { name: m.source_tree_collapse({ name: "A" }), exact: true })
    .click();
  await expect
    .element(page.getByRole("link", { name: folderName("nested", 20) }))
    .not.toBeInTheDocument();
});

test("a deep link rendered on the server does not fetch its selection again", async () => {
  api.route.url = new URL(
    `http://localhost/?tab=blobs&prefix=${encodeURIComponent(origin + "A/")}`
  );
  render(WebsiteContent, {
    websiteId: "website",
    initialPage: result(),
    initialContent: { prefix: origin + "A/", q: "", page: result([content("guide.pdf", "A/")]) }
  });
  await expect.element(page.getByRole("button", { name: "guide.pdf" })).toBeVisible();
  await expect
    .element(page.getByRole("link", { name: folderName("A", 40) }))
    .toHaveAttribute("aria-current", "page");
  expect(api.list).not.toHaveBeenCalled();
  await page.getByRole("link", { name: folderName("B", 80) }).click();
  expect(api.list).toHaveBeenCalledExactlyOnceWith({
    id: "website",
    limit: 100,
    cursor: null,
    prefix: origin + "B/"
  });
});
