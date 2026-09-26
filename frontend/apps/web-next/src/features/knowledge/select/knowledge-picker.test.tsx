// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeCollection, makeSpace, makeWebsite } from "@/features/spaces/testing/space-fixture";
import type { Collection, Website } from "../knowledge";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  }
}));

import { KnowledgePicker } from "./knowledge-picker";

afterEach(cleanup);

describe("KnowledgePicker", () => {
  it("counts the selected knowledge with plural forms", () => {
    const collection = makeCollection({ metadata: { num_info_blobs: 1, size: 10 } });
    const website = makeWebsite({
      latest_crawl: {
        ...(makeWebsite().latest_crawl as Record<string, unknown>),
        pages_crawled: 1,
        pages_failed: 1
      }
    });
    state.space = makeSpace({ collections: [collection], websites: [website] });

    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{
          collections: [collection as unknown as Collection],
          websites: [website as unknown as Website],
          integrationKnowledge: []
        }}
        onChange={() => {}}
      />
    );

    expect(screen.getByText("1 fil")).toBeTruthy();
    expect(screen.getByText("1 sida")).toBeTruthy();
    expect(screen.getByText("1 sida misslyckades")).toBeTruthy();
  });
});
