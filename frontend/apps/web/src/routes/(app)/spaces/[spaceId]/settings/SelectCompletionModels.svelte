<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { linkedSpaceModelIds } from "$lib/features/spaces/spaceModelAvailability";
  import type { CompletionModel } from "@eneo/eneo-js";
  import ModelAvailabilityList from "$lib/features/ai-models/components/ModelAvailabilityList.svelte";
  import type { LinkedModelRow } from "$lib/features/ai-models/linkedModelRow";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { SvelteSet } from "svelte/reactivity";

  export let selectableModels: (
    | (CompletionModel & {
        meets_security_classification?: boolean | null | undefined;
      })
    | LinkedModelRow
  )[];

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const currentlySelectedModels = derived(currentSpace, ($currentSpace) =>
    linkedSpaceModelIds($currentSpace, "completion")
  );

  let loading = new SvelteSet<string>();
  async function toggleModel(model: { id: string }) {
    loading.add(model.id);
    loading = loading;

    try {
      // Without the space's link state a save would unlink every model it
      // does not name, so refuse it rather than assume there are none.
      if ($currentlySelectedModels === null) {
        throw new Error(m.failed_to_load_models());
      }
      if ($currentlySelectedModels.includes(model.id)) {
        const newModels = $currentlySelectedModels
          .filter((id) => id !== model.id)
          .map((id) => {
            return { id };
          });
        await updateSpace({ completion_models: newModels });
      } else {
        const newModels = [...$currentlySelectedModels, model.id].map((id) => {
          return { id };
        });
        await updateSpace({ completion_models: newModels });
      }
    } catch (e) {
      toastError(e);
    }
    loading.delete(model.id);
    loading = loading;
  }
</script>

<Settings.Row title={m.completion_models()} description={m.completion_models_description()}>
  <svelte:fragment slot="description">
    {#if $currentSpace.completion_models.length === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>{m.enable_completion_model_for_assistants()}
      </p>
    {/if}
  </svelte:fragment>

  {#if $currentlySelectedModels === null}
    <!-- No link state: a save would unlink what it cannot see, so none is offered. -->
    <p role="alert" class="text-negative-default text-sm">{m.failed_to_load_models()}</p>
  {:else}
    <ModelAvailabilityList
      models={selectableModels}
      selectedIds={$currentlySelectedModels}
      loadingIds={loading}
      onToggle={toggleModel}
    />
  {/if}
</Settings.Row>
