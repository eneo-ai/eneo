<!--
    The assistant's own attachments in its editor: the fixed-context meter and
    the attachment list with each file's reading mode.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { getAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import ConfigContextMeter from "$lib/features/assistants/components/ConfigContextMeter.svelte";
  import AttachmentsEditor from "$lib/features/attachments/components/AttachmentsEditor.svelte";

  type Props = {
    fileReferencesEnabled: boolean;
    selectedModel?: { id: string; max_input_tokens: number; supports_tool_calling?: boolean };
    /** Set by the attachment list; bind it and call it after saving or discarding. */
    cancelUploadsAndClearQueue?: () => void;
  };
  let {
    fileReferencesEnabled,
    selectedModel,
    cancelUploadsAndClearQueue = $bindable()
  }: Props = $props();

  const {
    state: { update, resource }
  } = getAssistantEditor();
</script>

<ConfigContextMeter
  assistantId={$resource.id}
  model={selectedModel}
  prompt={$update.prompt.text}
  attachments={$update.attachments}
></ConfigContextMeter>

<section aria-labelledby="material-attachments-heading">
  <h4 id="material-attachments-heading" class="font-medium">{m.attachments()}</h4>
  <p class="text-secondary mt-1 mb-3 text-sm">{m.material_attachments_description()}</p>

  <AttachmentsEditor
    bind:attachments={$update.attachments}
    allowedAttachments={$update.allowed_attachments}
    bind:cancelUploadsAndClearQueue
    attachmentMode={{ fileReferencesEnabled, selectedModel }}
  />
</section>
