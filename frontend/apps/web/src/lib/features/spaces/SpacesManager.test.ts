import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));

import { SpacesManager } from "./SpacesManager";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (e: unknown) => void;
};
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const modelA = { id: "model-a", nickname: "A" };
const modelB = { id: "model-b", nickname: "B" };
const modelC = { id: "model-c", nickname: "C" };

function space(defaultAssistant: Record<string, unknown>) {
  return {
    id: "space-1",
    personal: true,
    organization: false,
    members: { items: [] },
    permissions: [],
    skill_permissions: [],
    applications: null,
    knowledge: {
      groups: { items: [], permissions: [] },
      websites: { items: [], permissions: [] },
      integration_knowledge_list: { items: [], permissions: [] }
    },
    completion_models: [modelA, modelB, modelC],
    default_assistant: defaultAssistant
  } as never;
}

function manager(update: (...args: unknown[]) => Promise<unknown>) {
  const eneo = { assistants: { update }, spaces: {} } as never;
  return SpacesManager({
    spaces: [],
    currentSpace: space({ id: "assistant-1", completion_model: modelA }),
    eneo
  });
}

describe("SpacesManager.updateDefaultAssistant", () => {
  it("shows the new model at once but only reports settled after the server confirms it", async () => {
    const pending = deferred<Record<string, unknown>>();
    const m = manager(() => pending.promise);

    const done = m.updateDefaultAssistant({ completionModel: { id: "model-b" } });
    let settled = false;
    void m.awaitDefaultAssistantUpdates().then(() => (settled = true));

    // The queued update starts on the next microtask and applies the
    // optimistic model before its request is awaited.
    await Promise.resolve();
    expect(get(m.state.currentSpace).default_assistant?.completion_model).toEqual(modelB);
    expect(settled).toBe(false);

    pending.resolve({ id: "assistant-1", completion_model: modelB });
    await done;
    expect(settled).toBe(true);
    expect(get(m.state.currentSpace).default_assistant?.completion_model).toEqual(modelB);
  });

  it("applies quick successive switches in order so the last choice wins", async () => {
    const calls: Deferred<Record<string, unknown>>[] = [];
    const m = manager(() => {
      const d = deferred<Record<string, unknown>>();
      calls.push(d);
      return d.promise;
    });

    void m.updateDefaultAssistant({ completionModel: { id: "model-b" } });
    void m.updateDefaultAssistant({ completionModel: { id: "model-c" } });
    await Promise.resolve();
    // The second update waits for the first; only one request is in flight.
    expect(calls).toHaveLength(1);

    calls[0].resolve({ id: "assistant-1", completion_model: modelB });
    await vi.waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve({ id: "assistant-1", completion_model: modelC });
    await m.awaitDefaultAssistantUpdates();

    expect(get(m.state.currentSpace).default_assistant?.completion_model).toEqual(modelC);
  });

  it("rolls the optimistic choice back and still settles when the update fails", async () => {
    const m = manager(() => Promise.reject(new Error("nope")));

    await m.updateDefaultAssistant({ completionModel: { id: "model-b" } });
    await m.awaitDefaultAssistantUpdates();

    expect(get(m.state.currentSpace).default_assistant?.completion_model).toEqual(modelA);
  });
});

describe("SpacesManager.updateSpace", () => {
  const links = (ids: string[]) => ids.map((id) => ({ id, name: id, available: true }));
  function linkedSpace(completion: string[], embedding: string[]) {
    return {
      ...(space({ id: "assistant-1", completion_model: modelA }) as Record<string, unknown>),
      completion_models: completion.map((id) => ({ id })),
      embedding_models: embedding.map((id) => ({ id })),
      linked_models: {
        completion_models: links(completion),
        embedding_models: links(embedding),
        transcription_models: []
      }
    } as never;
  }
  function spacesManager(spaces: Record<string, unknown>) {
    return SpacesManager({
      spaces: [],
      currentSpace: linkedSpace([], []),
      eneo: { assistants: {}, spaces } as never
    });
  }
  // What a model section sends: its own list, built from the space as it
  // stands when the update starts.
  const adding =
    (field: "completion_models" | "embedding_models", id: string) =>
    (current: { linked_models?: Record<string, { id: string }[]> }) => ({
      [field]: [...(current.linked_models?.[field] ?? []).map((l) => l.id), id].map((i) => ({
        id: i
      }))
    });

  it("keeps both sections' links when their saves overlap", async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    const update = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const m = spacesManager({ update });

    const completionSave = m.updateSpace(adding("completion_models", "c1"));
    const embeddingSave = m.updateSpace(adding("embedding_models", "e1"));
    await Promise.resolve();
    // The second update waits for the first to settle.
    expect(update).toHaveBeenCalledTimes(1);

    first.resolve(linkedSpace(["c1"], []));
    await completionSave;
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls[1][0]).toEqual({
      space: { id: "space-1" },
      update: { embedding_models: [{ id: "e1" }] }
    });
    second.resolve(linkedSpace(["c1"], ["e1"]));
    await embeddingSave;

    const shown = get(m.state.currentSpace);
    expect(shown.completion_models.map((model) => model.id)).toEqual(["c1"]);
    expect(shown.embedding_models.map((model) => model.id)).toEqual(["e1"]);
  });

  function otherSpace() {
    return { ...(linkedSpace([], []) as Record<string, unknown>), id: "space-2" } as never;
  }

  it("keeps a response away from the space the user moved to", async () => {
    const saving = deferred<unknown>();
    const m = spacesManager({ update: () => saving.promise });

    const save = m.updateSpace({ completion_models: [{ id: "c1" }] });
    m.watchPageData({ currentSpace: otherSpace() });
    saving.resolve(linkedSpace(["c1"], []));

    expect((await save)?.id).toBe("space-1");
    expect(get(m.state.currentSpace).id).toBe("space-2");
  });

  it("builds a queued edit from its own space after the user moved on", async () => {
    const first = deferred<unknown>();
    const update = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(async () => linkedSpace(["c1"], ["e1"]));
    const fetched = vi.fn(async ({ id }: { id: string }) => ({
      ...(linkedSpace(["c1"], []) as Record<string, unknown>),
      id
    }));
    const m = spacesManager({ update, get: fetched });

    m.updateSpace(adding("completion_models", "c1"));
    const queued = m.updateSpace(adding("embedding_models", "e1"));
    m.watchPageData({ currentSpace: otherSpace() });
    first.resolve(linkedSpace(["c1"], []));
    await queued;

    // The queued edit went to space-1, built from space-1 as the server has it.
    expect(fetched).toHaveBeenCalledWith({ id: "space-1" });
    expect(update.mock.calls[1][0]).toEqual({
      space: { id: "space-1" },
      update: { embedding_models: [{ id: "e1" }] }
    });
    expect(get(m.state.currentSpace).id).toBe("space-2");
  });

  it("drops a read of a space the user has left", async () => {
    const read = deferred<unknown>();
    const m = spacesManager({ get: () => read.promise });

    const refresh = m.refreshCurrentSpace();
    m.watchPageData({ currentSpace: otherSpace() });
    read.resolve(linkedSpace(["c1"], []));
    await refresh;

    expect(get(m.state.currentSpace).id).toBe("space-2");
  });

  it("drops a read that started before an update it would overwrite", async () => {
    const read = deferred<unknown>();
    const m = spacesManager({
      get: () => read.promise,
      update: async () => linkedSpace(["c1"], [])
    });

    const refresh = m.refreshCurrentSpace();
    await m.updateSpace({ completion_models: [{ id: "c1" }] });
    read.resolve(linkedSpace([], []));
    await refresh;

    expect(get(m.state.currentSpace).completion_models.map((model) => model.id)).toEqual(["c1"]);
  });
});
