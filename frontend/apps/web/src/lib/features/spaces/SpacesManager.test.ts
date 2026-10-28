import { get } from "svelte/store";
import { createEneo, type Space } from "@eneo/eneo-js";
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

describe("SpacesManager.organizationSpaceId", () => {
  it("uses the current-space contract without needing organization membership and follows navigation", () => {
    const currentSpace = {
      id: "current",
      name: "Current space",
      description: null,
      personal: false,
      organization: false,
      organization_space_id: "org",
      embedding_models: [],
      completion_models: [],
      transcription_models: [],
      knowledge: {
        groups: { items: [], count: 0 },
        websites: { items: [], count: 0 },
        integration_knowledge_list: { items: [], count: 0 }
      },
      members: { items: [], count: 0 },
      group_members: { items: [], count: 0 },
      skill_permissions: [],
      available_roles: [],
      security_classification: null
    } satisfies Space;
    const m = SpacesManager({
      currentSpace,
      spaces: [],
      eneo: createEneo({ baseUrl: "https://eneo.invalid" })
    });

    expect(get(m.state.organizationSpaceId)).toBe("org");
    m.watchPageData({
      currentSpace: { ...currentSpace, id: "unlinked", organization_space_id: null }
    });
    expect(get(m.state.organizationSpaceId)).toBeNull();
  });
});

describe("SpacesManager.refreshCurrentSpace", () => {
  const initial: Space = {
    id: "space-a",
    name: "A",
    description: null,
    personal: false,
    organization: false,
    organization_space_id: null,
    embedding_models: [],
    completion_models: [],
    transcription_models: [],
    knowledge: {
      groups: { items: [], count: 0 },
      websites: { items: [], count: 0 },
      integration_knowledge_list: { items: [], count: 0 }
    },
    members: { items: [], count: 0 },
    group_members: { items: [], count: 0 },
    skill_permissions: [],
    available_roles: [],
    security_classification: null
  };

  function setup() {
    const eneo = createEneo({ baseUrl: "https://eneo.invalid" });
    const manager = SpacesManager({ currentSpace: initial, spaces: [], eneo });
    return { manager, eneo };
  }

  it.each([false, true])(
    "discards an old read after navigation, including A → B → A (%s)",
    async (returnToA) => {
      const { manager, eneo } = setup();
      const response = deferred<Space["knowledge"]>();
      vi.spyOn(eneo.spaces, "listKnowledge").mockReturnValue(response.promise);
      const refresh = manager.refreshCurrentSpace("knowledge");
      manager.watchPageData({ currentSpace: { ...initial, id: "space-b", name: "B" } });
      if (returnToA) manager.watchPageData({ currentSpace: { ...initial, name: "New A" } });
      response.resolve(initial.knowledge);
      expect(await refresh).toBe(false);
      expect(get(manager.state.currentSpace).name).toBe(returnToA ? "New A" : "B");
    }
  );

  it.each([false, true])(
    "does not replace the current space with a rename started before navigation (%s)",
    async (returnToA) => {
      const { manager, eneo } = setup();
      const response = deferred<Space>();
      vi.spyOn(eneo.spaces, "update").mockReturnValue(response.promise);
      const mutation = manager.updateSpace({ name: "Renamed" });
      manager.watchPageData({ currentSpace: { ...initial, id: "space-b", name: "B" } });
      if (returnToA) manager.watchPageData({ currentSpace: { ...initial, name: "New A" } });
      response.resolve({ ...initial, name: "Renamed" });
      expect((await mutation)?.name).toBe("Renamed");
      expect(get(manager.state.currentSpace).name).toBe(returnToA ? "New A" : "B");
    }
  );

  it("keeps the newest successful response when requests finish out of order", async () => {
    const { manager, eneo } = setup();
    const old = deferred<Space>();
    vi.spyOn(eneo.spaces, "get")
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ ...initial, name: "Newest" });
    const earlier = manager.refreshCurrentSpace();
    expect(await manager.refreshCurrentSpace()).toBe(true);
    old.resolve({ ...initial, name: "Stale" });
    expect(await earlier).toBe(false);
    expect(get(manager.state.currentSpace).name).toBe("Newest");
  });

  it("does not let a full read overwrite a newer knowledge refresh", async () => {
    const { manager, eneo } = setup();
    const old = deferred<Space>();
    vi.spyOn(eneo.spaces, "get").mockReturnValue(old.promise);
    vi.spyOn(eneo.spaces, "listKnowledge").mockResolvedValue(initial.knowledge);
    const earlier = manager.refreshCurrentSpace();
    expect(await manager.refreshCurrentSpace("knowledge")).toBe(true);
    old.resolve({ ...initial, name: "Stale" });
    expect(await earlier).toBe(false);
    expect(get(manager.state.currentSpace).name).toBe("A");
  });

  it("does not let a full read that began before a rename undo it", async () => {
    const { manager, eneo } = setup();
    const old = deferred<Space>();
    vi.spyOn(eneo.spaces, "get").mockReturnValue(old.promise);
    vi.spyOn(eneo.spaces, "update").mockResolvedValue({ ...initial, name: "Renamed" });
    const earlier = manager.refreshCurrentSpace();
    await manager.updateSpace({ name: "Renamed" });
    old.resolve({ ...initial, name: "A" });
    expect(await earlier).toBe(false);
    expect(get(manager.state.currentSpace).name).toBe("Renamed");
  });

  it("merges a partial response into the current space, preserving intervening edits", async () => {
    const { manager, eneo } = setup();
    const response = deferred<Space["knowledge"]>();
    vi.spyOn(eneo.spaces, "listKnowledge").mockReturnValue(response.promise);
    vi.spyOn(eneo.spaces, "update").mockResolvedValue({ ...initial, name: "Renamed" });
    const refresh = manager.refreshCurrentSpace("knowledge");
    await manager.updateSpace({ name: "Renamed" });
    response.resolve(initial.knowledge);
    expect(await refresh).toBe(true);
    expect(get(manager.state.currentSpace).name).toBe("Renamed");
  });
});
