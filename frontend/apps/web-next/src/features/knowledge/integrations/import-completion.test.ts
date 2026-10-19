// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "next-intl";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import { makeSpace, makeIntegration } from "@/features/spaces/testing/space-fixture";
import { testQueryClient } from "@/test/render";
import type { IntegrationKnowledge } from "../knowledge";
import {
  createPendingImports,
  describeImportOutcome,
  PENDING_IMPORTS_STORAGE_KEY,
  pendingImports,
  resetPendingImports,
  reportImports,
  trackImports,
  untrackImports,
  type PendingImport
} from "./import-completion";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(
  metadata: Partial<Metadata>,
  fields: Partial<IntegrationKnowledge> = {}
): IntegrationKnowledge {
  return {
    id: "ik-1",
    name: "Protokoll 2026",
    integration_type: "sharepoint",
    wrapper_id: null,
    ...fields,
    metadata: { size: 0, ...metadata }
  } as IntegrationKnowledge;
}

function pending(jobId: string): PendingImport {
  return { jobId, knowledgeId: `ik-${jobId}`, name: jobId, spaceRouteId: "space-1" };
}

function fakeStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => void entries.set(key, value),
    removeItem: (key) => void entries.delete(key),
    clear: () => entries.clear(),
    key: () => null,
    get length() {
      return entries.size;
    }
  };
}

afterEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  resetPendingImports();
});

describe("pending imports", () => {
  it("tracks each job once, forgets it on request and keeps the list in session storage", () => {
    trackImports([pending("a"), pending("b")]);
    trackImports([pending("b")]);
    expect(pendingImports().map((item) => item.jobId)).toEqual(["a", "b"]);
    untrackImports(["a"]);
    expect(pendingImports().map((item) => item.jobId)).toEqual(["b"]);

    // The next page load in this tab finds it again.
    resetPendingImports();
    expect(pendingImports()).toEqual([pending("b")]);
    untrackImports(["b"]);
    expect(sessionStorage.getItem(PENDING_IMPORTS_STORAGE_KEY)).toBeNull();
  });

  it("starts empty when the stored list is unreadable or storage is unavailable", () => {
    const garbage = fakeStorage();
    garbage.setItem(PENDING_IMPORTS_STORAGE_KEY, "{not json");
    expect(createPendingImports(garbage).get()).toEqual([]);

    const partial = fakeStorage();
    partial.setItem(PENDING_IMPORTS_STORAGE_KEY, JSON.stringify([{ jobId: "a" }, pending("b")]));
    expect(createPendingImports(partial).get()).toEqual([pending("b")]);

    const blocked: Storage = {
      ...fakeStorage(),
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      }
    };
    const store = createPendingImports(blocked);
    store.set([pending("c")]);
    expect(store.get()).toEqual([pending("c")]);
    expect(createPendingImports(null).get()).toEqual([]);
  });
});

describe("describeImportOutcome", () => {
  it("reads the indexed and skipped counts from the sync summary", () => {
    const outcome = describeImportOutcome(
      knowledge({
        last_sync_status: "success",
        document_count: 12,
        last_sync_summary: {
          files_processed: 10,
          unchanged_items: 2,
          skipped_items: 2,
          skipped_total: 5
        }
      }),
      "space-1"
    );
    expect(outcome).toEqual({
      name: "Protokoll 2026",
      indexed: 12,
      skipped: 5,
      href: "/spaces/space-1/knowledge/integrations/ik-1",
      error: null,
      synced: true
    });
  });

  it("leads to Problems when files were skipped and nothing was indexed, in the item's wrapper", () => {
    const outcome = describeImportOutcome(
      knowledge(
        {
          last_sync_status: "success",
          document_count: 0,
          last_sync_summary: { files_processed: 0, skipped_items: 3 }
        },
        { wrapper_id: "w1" }
      ),
      "space-1"
    );
    expect(outcome).toMatchObject({ indexed: 0, skipped: 3 });
    expect(outcome.href).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=ik-1&tab=problems"
    );
  });

  it("falls back to the document count when the summary is missing", () => {
    const outcome = describeImportOutcome(
      knowledge({ last_sync_status: "success", document_count: 7 }),
      "space-1"
    );
    expect(outcome).toMatchObject({ indexed: 7, skipped: 0, synced: true });
  });

  it("carries the sync error and knows when nothing has synced yet", () => {
    expect(
      describeImportOutcome(
        knowledge({ last_sync_status: "error", last_sync_error: "Token expired" }),
        "space-1"
      )
    ).toMatchObject({ error: "Token expired", synced: true });
    expect(
      describeImportOutcome(knowledge({ last_sync_status: "never" }), "space-1")
    ).toMatchObject({ synced: false, error: null });
  });
});

it("reports other spaces even while one space is unavailable, without duplicate reports", async () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => {});
  const waiting = [
    { ...pending("bad"), spaceRouteId: "bad-space" },
    { ...pending("good"), spaceRouteId: "good-space" }
  ];
  trackImports(waiting);
  api.GET.mockImplementation(
    async (_path: string, options: { params: { path: { id: string } } }) => {
      if (options.params.path.id === "bad-space") throw new Error("unavailable");
      return {
        data: makeSpace({
          overrides: { id: "good-space" },
          integrations: [
            makeIntegration({
              id: "ik-good",
              space_id: "good-space",
              metadata: { size: 0, last_sync_status: "success", document_count: 3 }
            })
          ]
        }),
        response: new Response("{}")
      };
    }
  );
  const context = {
    queryClient: testQueryClient(),
    t: createTranslator({ locale: "sv", messages: sv as Record<string, string> }),
    navigate: vi.fn()
  };
  const settled = waiting.map((item) => ({ ...item, jobStatus: "complete" as const }));
  await Promise.all([reportImports(settled, context), reportImports(settled, context)]);
  expect(toast.success).toHaveBeenCalledTimes(1);
  expect(pendingImports()).toEqual([waiting[0]]);
  logged.mockRestore();
});

it("tells every import finishing in the same space in a toast of its own", async () => {
  const waiting = [pending("a"), pending("b")];
  trackImports(waiting);
  api.GET.mockResolvedValue({
    data: makeSpace({
      integrations: ["a", "b"].map((id) =>
        makeIntegration({
          id: `ik-${id}`,
          name: id === "a" ? "Avtal" : "Policy",
          metadata: { size: 0, last_sync_status: "success", document_count: 3 }
        })
      )
    }),
    response: new Response("{}")
  });
  await reportImports(
    waiting.map((item) => ({ ...item, jobStatus: "complete" })),
    {
      queryClient: testQueryClient(),
      t: createTranslator({ locale: "sv", messages: sv as Record<string, string> }),
      navigate: vi.fn()
    }
  );
  // The toaster's live region speaks them; nothing else says them again.
  expect(toast.success).toHaveBeenCalledTimes(2);
  expect(toast.success.mock.calls.map(([message]) => message)).toEqual([
    expect.stringContaining("Avtal:"),
    expect.stringContaining("Policy:")
  ]);
  expect(pendingImports()).toEqual([]);
});

it("words the documents of an import result in the singular and the plural", async () => {
  const waiting = [pending("a"), pending("b")];
  trackImports(waiting);
  api.GET.mockResolvedValue({
    data: makeSpace({
      integrations: [
        makeIntegration({
          id: "ik-a",
          name: "Avtal",
          metadata: { size: 0, last_sync_status: "success", document_count: 1 }
        }),
        makeIntegration({
          id: "ik-b",
          name: "Policy",
          metadata: { size: 0, last_sync_status: "success", document_count: 3 }
        })
      ]
    }),
    response: new Response("{}")
  });
  await reportImports(
    waiting.map((item) => ({ ...item, jobStatus: "complete" })),
    {
      queryClient: testQueryClient(),
      t: createTranslator({ locale: "en", messages: en as Record<string, string> }),
      navigate: vi.fn()
    }
  );
  expect(toast.success.mock.calls.map(([message]) => message)).toEqual([
    "Avtal: 1 document indexed, 0 skipped",
    "Policy: 3 documents indexed, 0 skipped"
  ]);
});
