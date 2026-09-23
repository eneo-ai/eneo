<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { EneoError, type CompletionModel, type ModelKwargs, type Service } from "@eneo/eneo-js";
  import { Button, Select } from "@eneo/ui";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { makeEditable } from "$lib/core/editable";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import {
    filterSupportedModelKwargs,
    hasModelSpecificSettings
  } from "$lib/features/ai-models/ModelKwargCapabilities";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  export let service: Service;

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let editableService = makeEditable(service);
  let stringJsonSchema = editableService.json_schema
    ? JSON.stringify(editableService.json_schema)
    : "";
  let completionModel = service.completion_model as CompletionModel | null;
  let completionModelKwargs: ModelKwargs = service.completion_model_kwargs ?? {};

  const nameId = useId();
  const promptId = useId();
  const jsonSchemaId = useId();

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

    if (completionModel && completionModel.id !== service.completion_model?.id) {
      update.completion_model = { id: completionModel.id };
    }

    update.completion_model_kwargs = filterSupportedModelKwargs(
      completionModelKwargs,
      completionModel
    );

    try {
      await eneo.services.update({
        service: { id: service.id },
        update
      });
      invalidate("service:get");
    } catch (e) {
      if (e instanceof EneoError) {
        toast.error(e.message);
        console.error(e);
      }
    }
    updatingService = false;
  }
</script>

<div class="flex min-h-full flex-grow flex-col justify-start">
  <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
    <Field.Label for={nameId}>
      {m.name()}
      <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
    </Field.Label>
    <Input id={nameId} bind:value={editableService.name} required />
  </Field.Field>

  <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
    <Field.Label for={promptId}>
      {m.prompt()}
      <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
    </Field.Label>
    <Textarea
      id={promptId}
      bind:value={editableService.prompt}
      required
      rows={6}
      class="min-h-36"
    />
  </Field.Field>

  <div class="flex">
    <SelectAIModelV2
      bind:selectedModel={completionModel}
      availableModels={$currentSpace.completion_models}
    />

    <SelectBehaviourV2
      bind:kwArgs={completionModelKwargs}
      selectedModel={completionModel}
      isDisabled={!completionModel}
    />
  </div>

  {#if hasModelSpecificSettings(completionModel)}
    <SelectModelSpecificSettings
      bind:kwArgs={completionModelKwargs}
      selectedModel={completionModel}
    />
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
    <Field.Field class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4">
      <Field.Label for={jsonSchemaId}>{m.json_schema()}</Field.Label>
      <Textarea
        id={jsonSchemaId}
        bind:value={stringJsonSchema}
        rows={15}
        required
        class="min-h-80"
      />
    </Field.Field>
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
