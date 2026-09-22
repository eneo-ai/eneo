<script lang="ts">
  import { Input } from "@eneo/ui";
  import { Settings } from "$lib/components/layout";
  import { getAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    fileReferencesEnabled: boolean;
    modelSupportsTools: boolean;
  };
  let { fileReferencesEnabled, modelSupportsTools }: Props = $props();
  const {
    state: { update, currentChanges },
    discardChanges
  } = getAssistantEditor();
</script>

<div class="space-y-6">
  <Settings.Row
    fullWidth
    title={m.material_knowledge_timing()}
    description={m.material_knowledge_timing_description()}
    hasChanges={$currentChanges.diff.knowledge_mode !== undefined}
    revertFn={() => discardChanges("knowledge_mode")}
    let:aria
  >
    <div role="radiogroup" {...aria} class="border-default border-b py-2">
      <Input.RadioSwitch
        bind:value={
          () => $update.knowledge_mode === "tool",
          (on) => ($update.knowledge_mode = on ? "tool" : "inject")
        }
        labelTrue={m.material_when_needed()}
        labelFalse={m.material_before_each_answer()}
      />
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
    revertFn={() => discardChanges("inline_file_text")}
    let:aria
  >
    {#if fileReferencesEnabled}
      <div role="radiogroup" {...aria} class="border-default border-b py-2">
        <Input.RadioSwitch
          bind:value={() => !$update.inline_file_text, (on) => ($update.inline_file_text = !on)}
          labelTrue={m.material_open_when_needed()}
          labelFalse={m.material_read_directly()}
        />
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
