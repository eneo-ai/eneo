<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Paperclip } from "@lucide/svelte";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import OpenFilesHelp from "$lib/features/assistants/components/OpenFilesHelp.svelte";

  type Props = {
    /** "On" lets assistants read large attachments with a tool instead of
        inlining their whole text (backend: inline_file_text = false). The
        originals are served from whichever store holds them (PostgreSQL or
        object storage), so the switch needs no storage prerequisite. */
    openFilesEnabled: boolean;
    summary: string;
  };

  let { openFilesEnabled = $bindable(), summary }: Props = $props();
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
    <Switch id="files-large" bind:checked={openFilesEnabled} aria-describedby="files-large-help" />
  </div>
</PolicySection>
