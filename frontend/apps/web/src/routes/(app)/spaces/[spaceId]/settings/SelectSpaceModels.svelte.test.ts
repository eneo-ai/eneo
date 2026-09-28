import type { CompletionModel } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { get, writable, type Writable } from "svelte/store";
import { beforeEach, expect, it, vi } from "vitest";

const { currentSpace, updateSpace } = vi.hoisted(() => ({
  currentSpace: { value: null as unknown, store: null as unknown },
  updateSpace: vi.fn(async (_patch: unknown) => {})
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace: (currentSpace.store = writable(currentSpace.value)) },
    updateSpace
  })
}));

import SelectSpaceModels from "./SelectSpaceModels.svelte";
import { m } from "$lib/paraglide/messages";

const completionProps = {
  field: "completion_models" as const,
  title: "Completion models",
  description: "Models for assistants",
  hint: "Enable a model"
};

const model = (id: string, nickname: string) =>
  ({ id, name: id, nickname, org: "OpenAI", is_org_enabled: true }) as unknown as CompletionModel;

// The selector hands the manager a function of the space as it stands when the
// update starts; this is the patch it builds from the current store.
function sentPatch(call: number) {
  const update = updateSpace.mock.calls[call][0];
  return typeof update === "function"
    ? update(get(currentSpace.store as Writable<unknown>))
    : update;
}

beforeEach(() => {
  updateSpace.mockReset();
  updateSpace.mockImplementation(async (_patch: unknown) => {});
});

const link = (id: string) => ({
  id,
  name: id,
  meets_security_classification: true,
  available: true
});

const spaceLinking = (ids: string[]) => ({
  completion_models: ids.map((id) => model(id, `Model ${id.toUpperCase()}`)),
  linked_models: {
    completion_models: ids.map(link),
    embedding_models: [],
    transcription_models: []
  }
});

it("refuses to edit the model list when the space reports no link state", async () => {
  currentSpace.value = { completion_models: [] };
  render(SelectSpaceModels, { ...completionProps, selectableModels: [model("a", "Model A")] });

  await expect.element(page.getByRole("alert")).toHaveTextContent(m.failed_to_load_models());
  await expect.element(page.getByRole("switch")).not.toBeInTheDocument();
});

it("sends every reported link plus the toggled model", async () => {
  const link = (id: string, meets: boolean, available: boolean) => ({
    id,
    name: id,
    meets_security_classification: meets,
    available
  });
  currentSpace.value = {
    completion_models: [model("a", "Model A")],
    linked_models: {
      completion_models: [link("a", true, true), link("hidden", false, false)],
      embedding_models: [],
      transcription_models: []
    }
  };
  render(SelectSpaceModels, {
    ...completionProps,
    selectableModels: [model("a", "Model A"), model("b", "Model B")]
  });

  await page.getByRole("switch", { name: /Model B/ }).click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(1);
  expect(sentPatch(0)).toEqual({
    completion_models: [{ id: "a" }, { id: "hidden" }, { id: "b" }]
  });
});

it("names a linked model missing from the catalogue, even without a nickname", async () => {
  const { spaceSettingsModelRows } = await import("$lib/features/spaces/spaceModelAvailability");
  const link = {
    id: "gone",
    name: "gpt-retired-route",
    nickname: null,
    meets_security_classification: false,
    available: true
  };
  currentSpace.value = {
    completion_models: [],
    linked_models: { completion_models: [link], embedding_models: [], transcription_models: [] }
  };
  render(SelectSpaceModels, {
    ...completionProps,
    selectableModels: spaceSettingsModelRows([model("a", "Model A")], [link])
  });

  const row = page.getByRole("switch", { name: /gpt-retired-route/ });
  await expect.element(row).toBeChecked();
  await row.click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(1);
  expect(sentPatch(0)).toEqual({ completion_models: [] });
});

it("holds every switch while a save is in flight, then works from the saved space", async () => {
  let finishSave = () => {};
  updateSpace.mockImplementationOnce(
    (_patch: unknown) =>
      new Promise<void>((resolve) => {
        finishSave = () => {
          (currentSpace.store as Writable<unknown>).set(spaceLinking(["a", "b"]));
          resolve();
        };
      })
  );
  currentSpace.value = spaceLinking(["a"]);
  render(SelectSpaceModels, {
    ...completionProps,
    selectableModels: [model("a", "Model A"), model("b", "Model B"), model("c", "Model C")]
  });

  await page.getByRole("switch", { name: /Model B/ }).click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(1);
  const other = page.getByRole("switch", { name: /Model C/ });
  await expect.element(other).toBeDisabled();
  // A second toggle built from the list before the first save would drop B.
  await other.click({ force: true });
  expect(updateSpace).toHaveBeenCalledTimes(1);

  finishSave();
  await expect.element(other).toBeEnabled();
  await other.click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(2);
  expect(sentPatch(1)).toEqual({
    completion_models: [{ id: "a" }, { id: "b" }, { id: "c" }]
  });
});
