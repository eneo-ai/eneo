<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import ModelAvailabilityList from "$lib/features/ai-models/components/ModelAvailabilityList.svelte";
  import { Settings } from "$lib/components/layout";
  import Hint from "$lib/components/Hint.svelte";
  import { toastError } from "$lib/core/errors";

  type Props = {
    field: "completion_models" | "embedding_models" | "transcription_models";
    selectableModels: ((CompletionModel | EmbeddingModel | TranscriptionModel) & {
      meets_security_classification?: boolean | null | undefined;
    })[];
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

  const selectedIds = $derived($currentSpace[field].map((model) => model.id));
  const loading = new SvelteSet<string>();

  async function toggleModel(model: { id: string }) {
    loading.add(model.id);
    try {
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
    {#if selectedIds.length === 0}
      <Hint class="mt-2.5">{hint}</Hint>
    {:else}
      {@render extra?.()}
    {/if}
  </svelte:fragment>

  <ModelAvailabilityList
    models={selectableModels}
    {selectedIds}
    loadingIds={loading}
    onToggle={toggleModel}
  />
</Settings.Row>
