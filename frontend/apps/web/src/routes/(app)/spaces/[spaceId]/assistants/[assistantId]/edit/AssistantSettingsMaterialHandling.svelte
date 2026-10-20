<!--
    When the assistant searches its knowledge sources, how the results are
    ordered, and how documents that users attach in chat are read.
-->
<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { getAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import { m } from "$lib/paraglide/messages";

  type RerankModel = components["schemas"]["RerankModelSecurityStatus"];
  type Props = {
    fileReferencesEnabled: boolean;
    modelSupportsTools: boolean;
    rerankModels?: RerankModel[];
  };
  let { fileReferencesEnabled, modelSupportsTools, rerankModels = [] }: Props = $props();
  const uid = $props.id();
  const {
    state: { resource, update, currentChanges }
  } = getAssistantEditor();

  // The backend refuses any other choice, so only these are offered.
  const selectableRerankModels = $derived(
    rerankModels.filter(
      (model) => model.can_access && model.meets_security_classification !== false
    )
  );
  const selectedRerankModel = $derived(
    selectableRerankModels.find((model) => model.id === $update.rerank_model_id)
  );
  const NO_RERANKER = "none";
</script>

<div class="space-y-6">
  <Settings.Row
    fullWidth
    title={m.material_knowledge_timing()}
    description={m.material_knowledge_timing_description()}
    hasChanges={$currentChanges.diff.knowledge_mode !== undefined}
    let:aria
  >
    <div class="border-default border-b py-2">
      <RadioGroup.Root
        value={$update.knowledge_mode === "tool" ? "on" : "off"}
        onValueChange={(v) => ($update.knowledge_mode = v === "on" ? "tool" : "inject")}
        class="grid w-full grid-cols-2 gap-2"
        {...aria}
      >
        <Field.Label for={`${uid}-knowledge-on`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="on" id={`${uid}-knowledge-on`} />
            <span>{m.material_when_needed()}</span>
          </Field.Field>
        </Field.Label>
        <Field.Label for={`${uid}-knowledge-off`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="off" id={`${uid}-knowledge-off`} />
            <span>{m.material_before_each_answer()}</span>
          </Field.Field>
        </Field.Label>
      </RadioGroup.Root>
    </div>
    {#if $update.knowledge_mode === "tool" && !modelSupportsTools}
      <p class="text-warning-stronger mt-2 text-sm">{m.material_knowledge_model_fallback()}</p>
    {/if}
  </Settings.Row>

  <!-- Kept while a saved choice exists, so clearing a stale one stays visible until saved. -->
  {#if selectableRerankModels.length > 0 || $update.rerank_model_id || $resource.rerank_model_id}
    <Settings.Row
      fullWidth
      title={m.material_reranker()}
      description={m.material_reranker_description()}
      hasChanges={$currentChanges.diff.rerank_model_id !== undefined}
      let:aria
    >
      <!-- A stale choice keeps its own value, so picking "none" is a real change. -->
      <Select.Root
        type="single"
        value={$update.rerank_model_id ?? NO_RERANKER}
        onValueChange={(v) => ($update.rerank_model_id = v === NO_RERANKER ? null : v)}
      >
        <Select.Trigger class="w-full" {...aria}>
          {selectedRerankModel?.nickname ??
            ($update.rerank_model_id ? m.material_reranker_missing() : m.material_reranker_none())}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value={NO_RERANKER} label={m.material_reranker_none()}>
            {m.material_reranker_none()}
          </Select.Item>
          {#each selectableRerankModels as model (model.id)}
            <Select.Item value={model.id} label={model.nickname}>{model.nickname}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
      {#if $update.rerank_model_id && !selectedRerankModel}
        <p class="text-warning-stronger mt-2 text-sm">{m.material_reranker_unavailable()}</p>
      {/if}
    </Settings.Row>
  {/if}

  <Settings.Row
    fullWidth
    title={m.material_chat_uploads()}
    description={m.material_upload_handling_description()}
    hasChanges={$currentChanges.diff.inline_file_text !== undefined}
    let:aria
  >
    {#if fileReferencesEnabled}
      <div class="border-default border-b py-2">
        <RadioGroup.Root
          value={$update.inline_file_text ? "off" : "on"}
          onValueChange={(v) => ($update.inline_file_text = v !== "on")}
          class="grid w-full grid-cols-2 gap-2"
          {...aria}
        >
          <Field.Label for={`${uid}-uploads-on`} class="font-normal">
            <Field.Field orientation="horizontal">
              <RadioGroup.Item value="on" id={`${uid}-uploads-on`} />
              <span>{m.material_open_when_needed()}</span>
            </Field.Field>
          </Field.Label>
          <Field.Label for={`${uid}-uploads-off`} class="font-normal">
            <Field.Field orientation="horizontal">
              <RadioGroup.Item value="off" id={`${uid}-uploads-off`} />
              <span>{m.material_read_directly()}</span>
            </Field.Field>
          </Field.Label>
        </RadioGroup.Root>
      </div>
    {:else}
      <p class="text-secondary text-sm">{m.material_upload_inline_summary()}</p>
    {/if}
    {#if !$update.inline_file_text && (!fileReferencesEnabled || !modelSupportsTools)}
      <p class="text-warning-stronger mt-2 text-sm">
        {fileReferencesEnabled
          ? m.material_file_model_fallback()
          : m.material_file_references_unavailable()}
      </p>
    {/if}
  </Settings.Row>
</div>
