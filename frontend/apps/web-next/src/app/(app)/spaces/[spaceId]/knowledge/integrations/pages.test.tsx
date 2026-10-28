// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import type { Space } from "@/features/spaces/space";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";

const state = vi.hoisted(() => ({
  space: null as unknown,
  error: null as unknown,
  requested: [] as unknown[]
}));
/** React's cache() memoizes for one server request; each test is one request. */
const request = vi.hoisted(() => ({ memos: [] as Map<string, unknown>[] }));
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    cache: <Args extends unknown[], Result>(fn: (...args: Args) => Result) => {
      const memo = new Map<string, Result>();
      request.memos.push(memo as Map<string, unknown>);
      return (...args: Args) => {
        const key = JSON.stringify(args);
        if (!memo.has(key)) memo.set(key, fn(...args));
        return memo.get(key) as Result;
      };
    }
  };
});
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));

vi.mock("@/lib/api/server", () => ({ eneoApi: () => ({}) }));
vi.mock("@/lib/api/query", () => ({
  getQueryClient: () => ({
    query: async ({ queryKey }: { queryKey: unknown[] }) => {
      state.requested.push(queryKey);
      if (state.error) throw state.error;
      return state.space;
    }
  })
}));
// Next's control flow throws; these stand-ins throw something a test can read.
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
  redirect: (url: string) => {
    throw new Error(`redirect ${url}`);
  },
  unstable_rethrow: () => {}
}));

import IntegrationsPage from "./page";
import IntegrationItemPage, {
  generateMetadata as itemMetadata
} from "./[integrationKnowledgeId]/page";
import WrapperPage, { generateMetadata as wrapperMetadata } from "./wrapper/[wrapperId]/page";

afterEach(() => {
  state.space = null;
  state.error = null;
  state.requested = [];
  for (const memo of request.memos) memo.clear();
});

function spaceWith(integrations: unknown[]): Space {
  return makeSpace({ integrations });
}

const itemPage = (integrationKnowledgeId: string, tab?: string) =>
  IntegrationItemPage({
    params: Promise.resolve({ spaceId: "space-1", integrationKnowledgeId }),
    searchParams: Promise.resolve(tab ? { tab } : {})
  });

const wrapperPage = (wrapperId: string) =>
  WrapperPage({ params: Promise.resolve({ spaceId: "space-1", wrapperId }) });

describe("the integrations route", () => {
  it("leads to the knowledge page's integrations tab", async () => {
    await expect(
      IntegrationsPage({ params: Promise.resolve({ spaceId: "personal" }) })
    ).rejects.toThrow("redirect /spaces/personal/knowledge?tab=integrations");
  });
});

describe("the item route", () => {
  it("shows an item imported on its own, as the server read it then", async () => {
    const item = makeIntegration({ id: "i1", name: "Avtal" });
    state.space = spaceWith([item]);
    const page = await itemPage("i1");
    // It stands in while the browser's space predates it (an item imported since).
    expect(page.props).toEqual({ itemId: "i1", loaded: { items: [item] } });
    expect(state.requested).toEqual([["spaces", "space-1"]]);
  });

  it("opens a wrapped SharePoint item as a folder of its source, on the tab asked for", async () => {
    state.space = spaceWith([
      makeIntegration({ id: "i1", wrapper_id: "w1", wrapper_name: "Byggnad" })
    ]);
    await expect(itemPage("i1", "skipped")).rejects.toThrow(
      "redirect /spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1&tab=problems"
    );
  });

  it("is not found for an unknown item, or one that belongs to another space", async () => {
    state.space = spaceWith([
      makeIntegration({ id: "i1" }),
      makeIntegration({ id: "shared", space_id: "space-2" })
    ]);
    await expect(itemPage("missing")).rejects.toThrow("not found");
    await expect(itemPage("shared")).rejects.toThrow("not found");
  });

  it("is not found when the space is", async () => {
    state.error = new EneoApiError("Space not found", { status: 404 });
    await expect(itemPage("i1")).rejects.toThrow("not found");
  });
});

describe("the wrapper route", () => {
  it("shows a wrapper of the space's own items, as the server read them then", async () => {
    const item = makeIntegration({ id: "i1", wrapper_id: "w1", wrapper_name: "Byggnad" });
    state.space = spaceWith([item]);
    const page = await wrapperPage("w1");
    expect(page.props).toEqual({ wrapperId: "w1", loaded: { items: [item] } });
  });

  it("is not found for an unknown wrapper, or one only another space's items are in", async () => {
    state.space = spaceWith([
      makeIntegration({ id: "i1", wrapper_id: "w1" }),
      makeIntegration({ id: "i2", wrapper_id: "w2", space_id: "space-2" })
    ]);
    await expect(wrapperPage("w9")).rejects.toThrow("not found");
    await expect(wrapperPage("w2")).rejects.toThrow("not found");
  });
});

describe("a source page and its title", () => {
  it("read the space once per request", async () => {
    state.space = spaceWith([
      makeIntegration({ id: "i1", name: "Avtal" }),
      makeIntegration({ id: "i2", wrapper_id: "w1", wrapper_name: "Byggnad" })
    ]);

    const item = { spaceId: "space-1", integrationKnowledgeId: "i1" };
    expect(await itemMetadata({ params: Promise.resolve(item) })).toEqual({ title: "Avtal" });
    await itemPage("i1");
    expect(state.requested).toEqual([["spaces", "space-1"]]);

    state.requested = [];
    const wrapper = { spaceId: "space-1", wrapperId: "w1" };
    expect(await wrapperMetadata({ params: Promise.resolve(wrapper) })).toEqual({
      title: "Byggnad"
    });
    await wrapperPage("w1");
    expect(state.requested).toEqual([["spaces", "space-1"]]);
  });
});
