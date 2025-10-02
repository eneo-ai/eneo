<script lang="ts">
  import { invalidate } from "$app/navigation";
  import SelectCompletionModel from "$lib/features/ai-models/components/SelectCompletionModel.svelte";
  import { IntricError, type Service } from "@intric/intric-js";
  import { Button, Input, Select } from "@intric/ui";
  import { makeEditable } from "$lib/core/editable";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SelectBehaviour from "$lib/features/ai-models/components/SelectBehaviour.svelte";
  import {
    getBehaviour,
    getKwargs,
    type ModelBehaviour
  } from "$lib/features/ai-models/ModelBehaviours";
  import SelectBehaviourCustom from "$lib/features/ai-models/components/SelectBehaviourCustom.svelte";
  import { m } from "$lib/paraglide/messages";

  export let service: Service;

  const intric = getIntric();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let editableService = makeEditable(service);
  let stringJsonSchema = editableService.json_schema
    ? JSON.stringify(editableService.json_schema)
    : "";

  const completion_model_config: {
    behaviour: ModelBehaviour;
    custom_kwargs: { temperature: number; top_p: number };
  } = {
    behaviour: getBehaviour(service.completion_model_kwargs),
    custom_kwargs: {
      temperature: service.completion_model_kwargs?.temperature ?? 1,
      top_p: service.completion_model_kwargs?.top_p ?? 1
    }
  };

  let updatingService = false;
  async function updateService() {
    if (editableService.output_format === "json" && stringJsonSchema === "") {
      return;
    }

    updatingService = true;
    const update = editableService.getEdits();
    if (editableService.output_format === "json") {
      if (stringJsonSchema !== JSON.stringify(editableService.json_schema)) {
        // Can't run diff on the schema, so we always include it completely
        update.json_schema = JSON.parse(stringJsonSchema);
      }
    } else {
      update.json_schema = undefined;
    }

    // Now overwrite custom settings
    update.completion_model_kwargs =
      getKwargs(completion_model_config.behaviour) ?? completion_model_config.custom_kwargs;

    try {
      await intric.services.update({
        service: { id: service.id },
        update
      });
      invalidate("service:get");
    } catch (e) {
      if (e instanceof IntricError) {
        alert(e.message);
        console.error(e);
      }
    }
    updatingService = false;
  }
</script>

<div class="flex min-h-full flex-grow flex-col justify-start">
  <Input.Text
    bind:value={editableService.name}
    label={m.name()}
    required
    class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
  ></Input.Text>

  <Input.TextArea
    bind:value={editableService.prompt}
    label={m.prompt()}
    required
    rows={6}
    class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
  ></Input.TextArea>

  <div class="flex">
    <SelectCompletionModel
      bind:value={editableService.completion_model}
      selectableModels={$currentSpace.completion_models}
    />

    <SelectBehaviour bind:value={completion_model_config.behaviour} />
  </div>

  {#if completion_model_config.behaviour == "custom"}
    <SelectBehaviourCustom bind:kwargs={completion_model_config.custom_kwargs} />
  {/if}

  <Select.Simple
    class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
    options={[
      { value: "json", label: "JSON" },
      { value: "list", label: m.list() },
      { value: "boolean", label: m.boolean() },
      { value: null, label: m.none() }
    ]}
    bind:value={editableService.output_format}>{m.output_format()}</Select.Simple
  >

  {#if editableService.output_format === "json"}
    <Input.TextArea
      bind:value={stringJsonSchema}
      class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
      rows={15}
      required
    >
      {m.json_schema()}</Input.TextArea
    >
  {/if}

  <div class="flex-grow"></div>
  <div
    class="sticky bottom-0 flex justify-end bg-gradient-to-t from-[var(--background-primary)] to-transparent p-4"
  >
    <Button variant="primary" on:click={updateService} class="w-[140px]">
      {#if updatingService}
        {m.saving()}
      {:else}
        {m.save()}
      {/if}
    </Button>
  </div>
</div>
