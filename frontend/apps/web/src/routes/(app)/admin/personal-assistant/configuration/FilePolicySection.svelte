<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { resolve } from "$app/paths";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Info, Paperclip } from "lucide-svelte";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import OpenFilesHelp from "$lib/features/assistants/components/OpenFilesHelp.svelte";

  type Props = {
    /** "On" lets assistants read large attachments with a tool instead of
        inlining their whole text (backend: inline_file_text = false). */
    openFilesEnabled: boolean;
    summary: string;
    /** Reading files with a tool needs the original files in object storage. */
    objectStoreConfigured: boolean;
    canConfigureStorage: boolean;
  };

  let {
    openFilesEnabled = $bindable(),
    summary,
    objectStoreConfigured,
    canConfigureStorage
  }: Props = $props();
</script>

<PolicySection
  id="files"
  title={m.governance_files_heading()}
  description={m.governance_files_section_desc()}
  {summary}
  summaryVariant="outline"
>
  {#snippet icon()}
    <Paperclip class="h-5 w-5" />
  {/snippet}

  <div class="flex items-start justify-between gap-4">
    <div>
      <Label for="files-large">{m.attachments_open_files_label()}</Label>
      <OpenFilesHelp id="files-large-help" />
    </div>
    <Switch
      id="files-large"
      bind:checked={openFilesEnabled}
      disabled={!objectStoreConfigured}
      aria-describedby="files-large-help"
    />
  </div>

  {#if !objectStoreConfigured}
    <Alert.Root class="border-caution/35 bg-caution/8">
      <Info class="text-caution" />
      <Alert.Description class="text-secondary">
        {m.attachments_open_files_storage_hint()}
        {#if canConfigureStorage}
          <a
            class="text-accent-default mt-1 inline-block underline"
            href={resolve("/admin/storage")}
          >
            {m.configure_object_storage()}
          </a>
        {/if}
      </Alert.Description>
    </Alert.Root>
  {/if}
</PolicySection>
