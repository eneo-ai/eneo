<script lang="ts">
  import type { EmbeddingModel } from "@eneo/eneo-js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  // Id of currently selected Embedding Model
  export let value: { id: string } | null | undefined;
  export let selectableModels: EmbeddingModel[];
  export let disabled: boolean = false;
  export let hideWhenNoOptions: boolean = false;

  const stableModels = selectableModels.filter((model) => model.stability === "stable");

  const experimentalModels = selectableModels.filter((model) => model.stability === "experimental");

  const triggerId = useId();

  function getModelDisplayName(model: EmbeddingModel) {
    if (model.open_source) {
      return `${model.name} (Open Source)`;
    }
    return model.name;
  }

  if (value) {
    if (!selectableModels.some((model) => model.id === value!.id)) {
      setTimeout(() => {
        toast.warning(m.embedding_model_no_longer_supported());
      }, 400);
    }
  } else if (selectableModels[0]) {
    // We assume stable models will always be there, this could be set to some default?
    value = { id: selectableModels[0].id };
  }

  $: selectedModel = selectableModels.find((model) => model.id === value?.id);
  $: unsupportedModelSelected = !!value && !selectedModel;

  function selectModel(id: string) {
    if (selectableModels.some((model) => model.id === id)) {
      value = { id };
    }
  }
</script>

{#if !(hideWhenNoOptions && selectableModels.length < 2)}
  <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
    <Field.Label for={triggerId}>{m.embedding_model()}</Field.Label>
    <Select.Root type="single" {disabled} value={value?.id ?? ""} onValueChange={selectModel}>
      <Select.Trigger
        id={triggerId}
        class="w-full"
        aria-invalid={unsupportedModelSelected || undefined}
      >
        {selectedModel ? getModelDisplayName(selectedModel) : m.no_model_selected()}
      </Select.Trigger>
      <Select.Content>
        <Select.Group>
          <Select.GroupHeading>{m.stable_embedding_models()}</Select.GroupHeading>
          {#each stableModels as model (model.id)}
            {@const modelName = getModelDisplayName(model)}
            <Select.Item value={model.id} label={modelName}>{modelName}</Select.Item>
          {:else}
            <Select.Item value="" disabled label={m.no_enabled_embedding_models()}>
              {m.no_enabled_embedding_models()}
            </Select.Item>
          {/each}
        </Select.Group>
        {#if experimentalModels.length > 0}
          <Select.Group>
            <Select.GroupHeading>{m.experimental_embedding_models()}</Select.GroupHeading>
            {#each experimentalModels as model (model.id)}
              {@const modelName = getModelDisplayName(model)}
              <Select.Item value={model.id} label={modelName}>{modelName}</Select.Item>
            {/each}
          </Select.Group>
        {/if}
      </Select.Content>
    </Select.Root>
  </Field.Field>
{/if}
