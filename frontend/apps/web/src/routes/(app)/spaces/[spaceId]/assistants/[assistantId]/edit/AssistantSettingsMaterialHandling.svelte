<!--
    When the assistant searches its knowledge sources, and how documents that
    users attach in chat are read.
-->
<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { getAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    fileReferencesEnabled: boolean;
    modelSupportsTools: boolean;
  };
  let { fileReferencesEnabled, modelSupportsTools }: Props = $props();
  const uid = $props.id();
  const {
    state: { update, currentChanges }
  } = getAssistantEditor();
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
