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
  // Each save sends the whole list, so a second toggle while one is in flight
  // would be built from the list before the first and drop its change. Every
  // switch waits for the save, then works from the space it returned.
  let saving = $state(false);

  async function toggleModel(model: { id: string }) {
    if (saving) return;
    saving = true;
    loading.add(model.id);
    try {
      // Without the space's link state a save would unlink every model it
      // does not name, so refuse it rather than assume there are none.
      if (linkedIds === null) {
        throw new Error(m.failed_to_load_models());
      }
      const adding = !selectedIds.includes(model.id);
      // Built when the update starts, from the space every earlier update
      // (another section's too) has returned.
      await updateSpace((latest) => {
        const current = linkedSpaceModelIds(latest, kinds[field]);
        if (current === null) throw new Error(m.failed_to_load_models());
        const ids = adding
          ? [...current.filter((id) => id !== model.id), model.id]
          : current.filter((id) => id !== model.id);
        return { [field]: ids.map((id) => ({ id })) };
      });
    } catch (e) {
      toastError(e);
    } finally {
      loading.delete(model.id);
      saving = false;
    }
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
      disabled={saving}
      onToggle={toggleModel}
    />
  {/if}
</Settings.Row>
