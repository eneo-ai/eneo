<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { TranscriptionModel } from "@eneo/eneo-js";
  import ModelAvailabilityList from "$lib/features/ai-models/components/ModelAvailabilityList.svelte";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { SvelteSet } from "svelte/reactivity";

  export let selectableModels: (TranscriptionModel & {
    meets_security_classification?: boolean | null | undefined;
  })[];

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const currentlySelectedModels = derived(
    currentSpace,
    ($currentSpace) => $currentSpace.transcription_models.map((model) => model.id) ?? []
  );

  let loading = new SvelteSet<string>();
  async function toggleModel(model: TranscriptionModel) {
    loading.add(model.id);
    loading = loading;

    try {
      if ($currentlySelectedModels.includes(model.id)) {
        const newModels = $currentlySelectedModels
          .filter((id) => id !== model.id)
          .map((id) => {
            return { id };
          });
        await updateSpace({ transcription_models: newModels });
      } else {
        const newModels = [...$currentlySelectedModels, model.id].map((id) => {
          return { id };
        });
        await updateSpace({ transcription_models: newModels });
      }
    } catch (e) {
      toastError(e);
    }
    loading.delete(model.id);
    loading = loading;
  }
</script>

<Settings.Row title={m.transcription_models()} description={m.transcription_models_description()}>
  <svelte:fragment slot="description">
    {#if $currentSpace.transcription_models.length === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>{m.transcription_models_hint()}
      </p>
    {/if}
  </svelte:fragment>

  <ModelAvailabilityList
    models={selectableModels}
    selectedIds={$currentlySelectedModels}
    loadingIds={loading}
    onToggle={toggleModel}
  />
</Settings.Row>
