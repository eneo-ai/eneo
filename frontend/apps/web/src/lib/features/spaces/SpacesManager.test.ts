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
