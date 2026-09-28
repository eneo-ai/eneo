<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { linkedSpaceModelIds } from "$lib/features/spaces/spaceModelAvailability";
  import type { LinkedModelRow } from "$lib/features/ai-models/linkedModelRow";
  import ModelAvailabilityList from "$lib/features/ai-models/components/ModelAvailabilityList.svelte";
  import { Settings } from "$lib/components/layout";
  import Hint from "$lib/components/Hint.svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    field: "completion_models" | "embedding_models" | "transcription_models";
    selectableModels: (
      | ((CompletionModel | EmbeddingModel | TranscriptionModel) & {
          meets_security_classification?: boolean | null | undefined;
        })
      | LinkedModelRow
    )[];
    title: string;
    description: string;
    /** Shown while the space has no model of this kind enabled. */
    hint: string;
    /** Rendered instead of the hint once at least one model is enabled. */
    extra?: Snippet;
  };

  const { field, selectableModels, title, description, hint, extra }: Props = $props();

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const kinds = {
    completion_models: "completion",
    embedding_models: "embedding",
    transcription_models: "transcription"
  } as const;
  // Every model the space links, whatever its state; null when the space came
  // without its link state.
  const linkedIds = $derived(linkedSpaceModelIds($currentSpace, kinds[field]));
  const selectedIds = $derived(linkedIds ?? []);
  const loading = new SvelteSet<string>();

  async function toggleModel(model: { id: string }) {
    loading.add(model.id);
    try {
      // Without the space's link state a save would unlink every model it
      // does not name, so refuse it rather than assume there are none.
      if (linkedIds === null) {
        throw new Error(m.failed_to_load_models());
      }
      const ids = selectedIds.includes(model.id)
        ? selectedIds.filter((id) => id !== model.id)
        : [...selectedIds, model.id];
      await updateSpace({ [field]: ids.map((id) => ({ id })) });
    } catch (e) {
      toastError(e);
    }
    loading.delete(model.id);
  }
</script>

<Settings.Row {title} {description}>
  <svelte:fragment slot="description">
    {#if $currentSpace[field].length === 0}
      <Hint class="mt-2.5">{hint}</Hint>
    {:else}
      {@render extra?.()}
    {/if}
  </svelte:fragment>

  {#if linkedIds === null}
    <!-- No link state: a save would unlink what it cannot see, so none is offered. -->
    <p role="alert" class="text-negative-default text-sm">{m.failed_to_load_models()}</p>
  {:else}
    <ModelAvailabilityList
      models={selectableModels}
      {selectedIds}
      loadingIds={loading}
      onToggle={toggleModel}
    />
  {/if}
</Settings.Row>
