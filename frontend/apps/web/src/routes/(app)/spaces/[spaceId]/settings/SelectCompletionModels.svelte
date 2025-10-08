<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { CompletionModel } from "@intric/intric-js";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { Input, Tooltip } from "@intric/ui";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { sortModels } from "$lib/features/ai-models/sortModels";
  import { m } from "$lib/paraglide/messages";

  export let selectableModels: (CompletionModel & {
    meets_security_classification?: boolean | null | undefined;
  })[];
  sortModels(selectableModels);

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const currentlySelectedModels = derived(
    currentSpace,
    ($currentSpace) => $currentSpace.completion_models.map((model) => model.id) ?? []
  );

  let loading = new Set<string>();
  async function toggleModel(model: CompletionModel) {
    loading.add(model.id);
    loading = loading;

    try {
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
      alert(e);
    }
    loading.delete(model.id);
    loading = loading;
  }
</script>

<Settings.Row
  title={m.completion_models()}
  description={m.completion_models_description()}
>
  <svelte:fragment slot="description">
    {#if $currentSpace.completion_models.length === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>{m.enable_completion_model_for_assistants()}
      </p>
    {/if}
  </svelte:fragment>

  {#each selectableModels as model (model.id)}
    {@const meetsClassification = model.meets_security_classification ?? true}
    <Tooltip
      text={meetsClassification
        ? undefined
        : m.model_does_not_meet_security_classification()}
    >
      <div
        class="border-default hover:bg-hover-dimmer cursor-pointer border-b py-4 pr-4 pl-2"
        class:pointer-events-none={!meetsClassification}
        class:opacity-60={!meetsClassification}
      >
        <Input.Switch
          value={$currentlySelectedModels.includes(model.id)}
          sideEffect={() => {
            if (meetsClassification) {
              toggleModel(model);
            }
          }}
        >
          <ModelNameAndVendor {model} />
        </Input.Switch>
      </div>
    </Tooltip>
  {/each}
</Settings.Row>
