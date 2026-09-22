<script lang="ts">
  import { untrack } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Assistant, Eneo } from "@eneo/eneo-js";
  import { initEneo } from "$lib/core/Eneo";
  import { initAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import AssistantSettingsAttachments from "./AssistantSettingsAttachments.svelte";
  import AssistantSettingsMaterialHandling from "./AssistantSettingsMaterialHandling.svelte";

  let {
    assistant,
    eneo,
    fileReferencesEnabled = true
  }: {
    assistant: Assistant;
    eneo: Eneo;
    fileReferencesEnabled?: boolean;
  } = $props();
  untrack(() => initEneo({ eneo }));
  const {
    state: { update, currentChanges },
    saveChanges,
    discardChanges
  } = untrack(() => initAssistantEditor({ assistant, eneo }));
  let supportsTools = $state(true);
  const selectedModel = $derived({
    id: "model",
    max_input_tokens: 32000,
    supports_tool_calling: supportsTools
  });
</script>

<AssistantSettingsAttachments {selectedModel} {fileReferencesEnabled} />
<AssistantSettingsMaterialHandling modelSupportsTools={supportsTools} {fileReferencesEnabled} />
<button onclick={() => (supportsTools = !supportsTools)}>{m.completion_model()}</button>
<button onclick={() => saveChanges()}>{m.save_changes()}</button>
<button onclick={() => discardChanges()}>{m.discard_all_changes()}</button>
<output data-testid="material-state"
  >{JSON.stringify({
    attachments: $update.attachments,
    inline_file_text: $update.inline_file_text,
    knowledge_mode: $update.knowledge_mode,
    dirty: $currentChanges.hasUnsavedChanges
  })}</output
>
