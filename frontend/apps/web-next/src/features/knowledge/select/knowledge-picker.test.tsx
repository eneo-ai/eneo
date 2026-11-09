// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import type { Space } from "@/features/spaces/space";
import {
  makeCollection,
  makeIntegration,
  makeSpace,
  makeWebsite
} from "@/features/spaces/testing/space-fixture";
import type { Collection, IntegrationKnowledge, Website } from "../knowledge";

const state = vi.hoisted(() => ({ space: null as unknown }));
const api = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { KnowledgePicker } from "./knowledge-picker";

beforeEach(() => {
  api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("KnowledgePicker", () => {
  it.each([
    {
      kind: "shared",
      personal: false,
      addLabel: "Lägg till kunskap (den här ytan)",
      emptyLabel: "Det finns inga tillgängliga källor i den här ytan."
    },
    {
      kind: "personal",
      personal: true,
      addLabel: "Lägg till kunskap (Personlig)",
      emptyLabel: "Inga personliga källor tillgängliga."
    }
  ])("names current-space knowledge in a $kind space", ({ personal, addLabel, emptyLabel }) => {
    state.space = makeSpace({ overrides: { personal } });

    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{ collections: [], websites: [], integrationKnowledge: [] }}
        onChange={() => {}}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: addLabel }));
    expect(screen.getByText(emptyLabel)).toBeTruthy();
  });

  it("keeps every selected source in exactly one picker, by the space that owns it", () => {
    const own = makeCollection({ id: "own", name: "Egen" });
    const org = makeCollection({ id: "org", name: "Gemensam", space_id: "org-space" });
    const legacy = makeCollection({ id: "legacy", name: "Lånad", space_id: "third-space" });
    state.space = makeSpace({
      collections: [own, org],
      overrides: { organization_space_id: "org-space" }
    });
    const selections = {
      collections: [own, org, legacy] as unknown as Collection[],
      websites: [],
      integrationKnowledge: []
    };
    const onChange = vi.fn();
    const view = (origin: "personal" | "organization") =>
      renderInApp(<KnowledgePicker origin={origin} selections={selections} onChange={onChange} />);

    view("personal");
    expect(screen.getByText("Egen")).toBeTruthy();
    expect(screen.getByText("Lånad")).toBeTruthy();
    expect(screen.queryByText("Gemensam")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Ta bort" })[1]!);
    expect(onChange).toHaveBeenCalledExactlyOnceWith({ ...selections, collections: [own, org] });
    cleanup();

    view("organization");
    expect(screen.getByText("Gemensam")).toBeTruthy();
    expect(screen.queryByText("Egen")).toBeNull();
    expect(screen.queryByText("Lånad")).toBeNull();
  });

  it("flags a source to add whose last sync failed or that holds nothing", () => {
    const synced = (status: string, document_count: number) => ({
      size: 0,
      last_synced_at: "2026-09-20T08:00:00Z",
      last_sync_status: status,
      document_count
    });
    state.space = makeSpace({
      integrations: [
        makeIntegration({ id: "failed", name: "Trasig", metadata: synced("error", 2) }),
        makeIntegration({ id: "empty", name: "Tomrum", metadata: synced("success", 0) }),
        makeIntegration({ id: "healthy", name: "Frisk", metadata: synced("success", 3) }),
        ...["ok", "error"].map((status) =>
          makeIntegration({
            id: `wrapped-${status}`,
            wrapper_id: "wrapper",
            wrapper_name: "Byggnad",
            metadata: synced(status, 1)
          })
        )
      ]
    });
    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{ collections: [], websites: [], integrationKnowledge: [] }}
        onChange={() => {}}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Lägg till kunskap (den här ytan)" }));
    expect(screen.getByRole("combobox", { name: "Sök kunskap" })).toBeTruthy();
    const option = (name: string) => screen.getByRole("option", { name: new RegExp(name) });
    expect(within(option("Trasig")).getByText("Synk misslyckades")).toBeTruthy();
    expect(within(option("Byggnad")).getByText("Synk misslyckades")).toBeTruthy();
    expect(within(option("Tomrum")).getByText("Tom")).toBeTruthy();
    expect(option("Frisk").textContent).toBe("Frisk");
  });

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

  it("expands selected integration items without changing selection and removes the whole wrapper", async () => {
    const integrations = [
      makeIntegration({
        id: "first",
        name: "Avtal",
        wrapper_id: "wrapper",
        wrapper_name: "Importerad kunskap",
        folder_path: "/Dokument/Avtal"
      }),
      makeIntegration({
        id: "second",
        name: "Policy.pdf",
        wrapper_id: "wrapper",
        wrapper_name: "Importerad kunskap",
        selected_item_type: "file"
      })
    ] as IntegrationKnowledge[];
    state.space = makeSpace({ integrations });
    const onChange = vi.fn();
    const { container } = renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{ collections: [], websites: [], integrationKnowledge: integrations }}
        onChange={onChange}
      />
    );
    const wrapper = screen.getByRole("button", { name: /Importerad kunskap/ });
    expect(wrapper.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(wrapper);
    expect(wrapper.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Avtal")).toBeTruthy();
    expect(screen.getByText("/Dokument/Avtal")).toBeTruthy();
    expect(screen.getByText("Policy.pdf")).toBeTruthy();
    await expectNoAxeViolations(container);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(wrapper);
    expect(wrapper.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Ta bort" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith({
      collections: [],
      websites: [],
      integrationKnowledge: []
    });
  });

  it("loads website cursors only on demand and retains earlier rows when the next page fails", async () => {
    const website = makeWebsite({ name: "Handbok" });
    state.space = makeSpace({ websites: [website] });
    const requests: { path: string; cursor: string | undefined }[] = [];
    let failMore = true;
    api.GET.mockImplementation(
      (path: string, options?: { params?: { query?: { cursor?: string } } }) => {
        if (path === "/api/v1/spaces/")
          return Promise.resolve({ data: { items: [] }, response: new Response("{}") });
        const cursor = options?.params?.query?.cursor;
        requests.push({ path, cursor });
        if (cursor && failMore)
          return Promise.resolve({
            error: { message: "Unavailable" },
            response: new Response("{}", { status: 503 })
          });
        const title = cursor ? "second.html" : "first.html";
        return Promise.resolve({
          data: {
            items: [{ id: title, metadata: { title } }],
            total_count: 2,
            next_cursor: cursor ? null : "next"
          },
          response: new Response("{}")
        });
      }
    );
    const onChange = vi.fn();
    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{
          collections: [],
          websites: [website as unknown as Website],
          integrationKnowledge: []
        }}
        onChange={onChange}
      />
    );
    expect(requests).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Handbok" }));
    expect(await screen.findByRole("button", { name: "first.html" })).toBeTruthy();
    expect(requests).toEqual([
      { path: "/api/v1/websites/{id}/info-blobs/page/", cursor: undefined }
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Läs in fler|Visa fler|Ladda fler/ }));
    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    expect(screen.getByRole("button", { name: "first.html" })).toBeTruthy();
    failMore = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: "second.html" })).toBeTruthy();
    expect(requests.map((request) => request.cursor)).toEqual([undefined, "next", "next"]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("cancels a website page when collapsed and ignores its late result", async () => {
    const website = makeWebsite({ name: "Handbok" });
    state.space = makeSpace({ websites: [website] });
    let signal: AbortSignal | undefined;
    let finish!: (value: unknown) => void;
    let pageRequests = 0;
    const reply = (title: string) => ({
      data: { items: [{ id: title, metadata: { title } }], total_count: 1, next_cursor: null },
      response: new Response("{}")
    });
    api.GET.mockImplementation((path: string, options?: { signal?: AbortSignal }) => {
      if (path === "/api/v1/spaces/")
        return Promise.resolve({ data: { items: [] }, response: new Response("{}") });
      pageRequests += 1;
      if (pageRequests > 1) return Promise.resolve(reply("fresh.html"));
      signal = options?.signal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{
          collections: [],
          websites: [website as unknown as Website],
          integrationKnowledge: []
        }}
        onChange={() => {}}
      />
    );
    const toggle = screen.getByRole("button", { name: "Handbok" });
    fireEvent.click(toggle);
    await waitFor(() => expect(signal).toBeDefined());
    fireEvent.click(toggle);
    await waitFor(() => expect(signal?.aborted).toBe(true));
    await act(async () => finish(reply("stale.html")));
    fireEvent.click(toggle);
    expect(await screen.findByRole("button", { name: "fresh.html" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "stale.html" })).toBeNull();
    expect(pageRequests).toBe(2);
  });
});
