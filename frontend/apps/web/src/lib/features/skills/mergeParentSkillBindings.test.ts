import type {
  App,
  Assistant,
  AssistantSkillBindingInput,
  Eneo,
  SkillBindingReferenceInput
} from "@eneo/eneo-js";
import { get } from "svelte/store";
import { describe, expect, test, vi } from "vitest";
import { initAppEditor } from "$lib/features/apps/AppEditor";
import { initAssistantEditor } from "$lib/features/assistants/AssistantEditor";

vi.mock("$lib/core/context", () => ({
  createContext: () => [() => undefined, () => undefined]
}));

type ParentUpdateRequest = {
  assistant?: Record<string, unknown>;
  app?: Record<string, unknown>;
  update: Record<string, unknown>;
};

function createTransport() {
  const updateParent = vi.fn(async (request: ParentUpdateRequest) => {
    const parent = request.assistant ?? request.app;
    if (!parent) throw new Error("A parent resource is required");

    return {
      ...Object.fromEntries(Object.entries(parent).filter(([key]) => key !== "skill_bindings")),
      ...Object.fromEntries(
        Object.entries(request.update).filter(([key]) => key !== "skill_bindings")
      )
    };
  });
  const skillWrite = vi.fn();
  const eneo = {
    assistants: { update: updateParent },
    apps: { update: updateParent },
    skills: {
      create: skillWrite,
      createRevision: skillWrite,
      setActive: skillWrite,
      delete: skillWrite
    },
    files: { delete: vi.fn() }
  } as unknown as Eneo;

  return { eneo, updateParent, skillWrite };
}

function createAssistantHarness(onUpdateDone = vi.fn()) {
  const transport = createTransport();
  const editor = initAssistantEditor({
    assistant: { id: "parent-1", name: "Original" } as unknown as Assistant,
    skillBindings: [
      {
        skill_id: "skill-1",
        skill_revision_id: "revision-1",
        activation_mode: "on_demand"
      }
    ],
    eneo: transport.eneo,
    onUpdateDone
  });

  return {
    ...transport,
    onUpdateDone,
    setBindings(bindings: AssistantSkillBindingInput[]) {
      editor.state.update.update((resource) => ({ ...resource, skill_bindings: bindings }));
    },
    setName(name: string) {
      editor.state.update.update((resource) => ({ ...resource, name }));
    },
    saveBindings: () => editor.saveChanges("skill_bindings"),
    saveAll: () => editor.saveChanges(),
    discardBindings: () => editor.discardChanges("skill_bindings"),
    persistedBindings: () => get(editor.state.resource).skill_bindings,
    draftBindings: () => get(editor.state.update).skill_bindings,
    hasUnsavedChanges: () => get(editor.state.currentChanges).hasUnsavedChanges
  };
}

function createAppHarness() {
  const transport = createTransport();
  const editor = initAppEditor({
    app: { id: "parent-1", name: "Original" } as unknown as App,
    skillBindings: [{ skill_id: "skill-1", skill_revision_id: "revision-1" }],
    eneo: transport.eneo
  });

  return {
    ...transport,
    setBindings(bindings: SkillBindingReferenceInput[]) {
      editor.state.update.update((resource) => ({ ...resource, skill_bindings: bindings }));
    },
    setName(name: string) {
      editor.state.update.update((resource) => ({ ...resource, name }));
    },
    saveBindings: () => editor.saveChanges("skill_bindings"),
    saveAll: () => editor.saveChanges(),
    discardBindings: () => editor.discardChanges("skill_bindings"),
    persistedBindings: () => get(editor.state.resource).skill_bindings,
    draftBindings: () => get(editor.state.update).skill_bindings,
    hasUnsavedChanges: () => get(editor.state.currentChanges).hasUnsavedChanges
  };
}

describe.each([
  { parentType: "Assistant", createHarness: createAssistantHarness },
  { parentType: "App", createHarness: createAppHarness }
])("$parentType Skill adapter", ({ createHarness }) => {
  test("persists exact ordered revisions once and keeps them through later saves and discard", async () => {
    const harness = createHarness();
    const orderedBindings = [
      { skill_id: "skill-2", skill_revision_id: "revision-2" },
      { skill_id: "skill-1", skill_revision_id: "revision-1" }
    ];

    harness.setBindings(orderedBindings);
    await expect(harness.saveBindings()).resolves.toBe(true);

    expect(harness.updateParent).toHaveBeenCalledTimes(1);
    expect(harness.updateParent.mock.calls[0]?.[0].update).toEqual({
      skill_bindings: orderedBindings
    });
    expect(harness.skillWrite).not.toHaveBeenCalled();
    expect(harness.persistedBindings()).toEqual(orderedBindings);
    expect(harness.draftBindings()).toEqual(orderedBindings);
    expect(harness.hasUnsavedChanges()).toBe(false);

    harness.setName("Renamed");
    await expect(harness.saveAll()).resolves.toBe(true);

    expect(harness.updateParent).toHaveBeenCalledTimes(2);
    expect(harness.updateParent.mock.calls[1]?.[0].update).toEqual({ name: "Renamed" });
    expect(harness.persistedBindings()).toEqual(orderedBindings);
    expect(harness.draftBindings()).toEqual(orderedBindings);
    expect(harness.hasUnsavedChanges()).toBe(false);

    harness.setBindings([{ skill_id: "skill-3", skill_revision_id: "revision-3" }]);
    expect(harness.hasUnsavedChanges()).toBe(true);
    harness.discardBindings();

    expect(harness.updateParent).toHaveBeenCalledTimes(2);
    expect(harness.skillWrite).not.toHaveBeenCalled();
    expect(harness.persistedBindings()).toEqual(orderedBindings);
    expect(harness.draftBindings()).toEqual(orderedBindings);
    expect(harness.hasUnsavedChanges()).toBe(false);
  });
});

test("Assistant Skill modes survive save, later parent edits, and discard", async () => {
  const harness = createAssistantHarness();
  const updatedBindings: AssistantSkillBindingInput[] = [
    {
      skill_id: "skill-1",
      skill_revision_id: "revision-2",
      activation_mode: "always"
    }
  ];

  harness.setBindings(updatedBindings);
  await expect(harness.saveBindings()).resolves.toBe(true);
  expect(harness.updateParent.mock.calls[0]?.[0].update).toEqual({
    skill_bindings: updatedBindings
  });

  harness.setName("Renamed");
  await expect(harness.saveAll()).resolves.toBe(true);
  expect(harness.persistedBindings()).toEqual(updatedBindings);

  harness.setBindings([
    {
      skill_id: "skill-1",
      skill_revision_id: "revision-2",
      activation_mode: "on_demand"
    }
  ]);
  harness.discardBindings();
  expect(harness.draftBindings()).toEqual(updatedBindings);
});

test("Assistant saves report the persisted fields to post-save projections", async () => {
  const harness = createAssistantHarness();
  const updatedBindings: AssistantSkillBindingInput[] = [
    {
      skill_id: "skill-1",
      skill_revision_id: "revision-2",
      activation_mode: "always"
    }
  ];

  harness.setBindings(updatedBindings);
  await expect(harness.saveBindings()).resolves.toBe(true);

  expect(harness.onUpdateDone).toHaveBeenCalledWith(expect.objectContaining({ id: "parent-1" }), {
    skill_bindings: updatedBindings
  });
});
