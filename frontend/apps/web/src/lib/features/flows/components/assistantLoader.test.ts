import { describe, expect, test, vi } from "vitest";
import { createAssistantLoader, type AssistantLoaderCallbacks } from "./assistantLoader";

type MockAssistant = { id: string; name: string };

function makeCallbacks(
  overrides: Partial<AssistantLoaderCallbacks<MockAssistant>> = {}
): AssistantLoaderCallbacks<MockAssistant> & {
  loaded: MockAssistant[];
  errors: unknown[];
  loadingStates: boolean[];
} {
  const loaded: MockAssistant[] = [];
  const errors: unknown[] = [];
  const loadingStates: boolean[] = [];
  return {
    loadAssistant: vi.fn(async (id: string) => ({ id, name: `Assistant ${id}` })),
    onLoaded: vi.fn((assistant) => loaded.push(assistant)),
    onError: vi.fn((error) => errors.push(error)),
    onLoadingChange: vi.fn((isLoading) => loadingStates.push(isLoading)),
    getCurrentAssistantId: vi.fn(() => "a1"),
    loaded,
    errors,
    loadingStates,
    ...overrides
  };
}

// ---------------------------------------------------------------------------
// Basic loading
// ---------------------------------------------------------------------------

describe("createAssistantLoader", () => {
  test("loads an assistant and fires callbacks", async () => {
    const cb = makeCallbacks();
    const loader = createAssistantLoader(cb);
    await loader.load("a1");

    expect(cb.loadAssistant).toHaveBeenCalledWith("a1");
    expect(cb.loaded).toEqual([{ id: "a1", name: "Assistant a1" }]);
    expect(cb.loadingStates).toEqual([true, false]);
  });

  test("does nothing for empty assistantId", async () => {
    const cb = makeCallbacks();
    const loader = createAssistantLoader(cb);
    await loader.load("");

    expect(cb.loadAssistant).not.toHaveBeenCalled();
  });

  test("fires onError when load fails", async () => {
    const err = new Error("network");
    const cb = makeCallbacks({
      loadAssistant: vi.fn(async () => {
        throw err;
      })
    });
    const loader = createAssistantLoader(cb);
    await loader.load("a1");

    expect(cb.errors).toHaveLength(1);
    expect(cb.loadingStates).toEqual([true, false]);
  });
});

// ---------------------------------------------------------------------------
// Cancellation via request token
// ---------------------------------------------------------------------------

describe("cancellation", () => {
  test("cancel() prevents stale load from firing callbacks", async () => {
    let resolve: ((val: MockAssistant) => void) | undefined;
    const cb = makeCallbacks({
      loadAssistant: vi.fn(
        () => new Promise<MockAssistant>((r) => {
          resolve = r;
        })
      )
    });
    const loader = createAssistantLoader(cb);

    const loadPromise = loader.load("a1");
    loader.cancel();
    resolve!({ id: "a1", name: "Stale" });
    await loadPromise;

    expect(cb.loaded).toEqual([]); // callback not called
  });

  test("concurrent loads cancel previous", async () => {
    let resolvers: Array<(val: MockAssistant) => void> = [];
    const cb = makeCallbacks({
      loadAssistant: vi.fn(
        () =>
          new Promise<MockAssistant>((r) => {
            resolvers.push(r);
          })
      ),
      getCurrentAssistantId: vi.fn(() => "a2") // simulates user switched to a2
    });
    const loader = createAssistantLoader(cb);

    const p1 = loader.load("a1");
    const p2 = loader.load("a2");

    // Resolve first load (stale)
    resolvers[0]({ id: "a1", name: "First" });
    await p1;
    expect(cb.loaded).toEqual([]); // first load discarded

    // Resolve second load (current)
    resolvers[1]({ id: "a2", name: "Second" });
    await p2;
    expect(cb.loaded).toEqual([{ id: "a2", name: "Second" }]);
  });

  test("discards load when getCurrentAssistantId mismatches", async () => {
    const cb = makeCallbacks({
      getCurrentAssistantId: vi.fn(() => "different-id")
    });
    const loader = createAssistantLoader(cb);
    await loader.load("a1");

    expect(cb.loaded).toEqual([]); // discarded due to id mismatch
  });
});
