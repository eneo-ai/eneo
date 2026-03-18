<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { UploadedFile } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { Button } from "@intric/ui";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconTrash } from "@intric/icons/trash";
  import { IconCancel } from "@intric/icons/cancel";
  import SelectKnowledgeV2 from "$lib/features/knowledge/components/SelectKnowledgeV2.svelte";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";

  export let assistant: any | null;
  export let assistantLoading: boolean;
  export let runningUploads: Array<{
    id: string;
    file: File;
    status: string;
    progress: number;
    remove: () => void;
  }>;

  const dispatch = createEventDispatcher<{
    knowledgeChange: {
      websites: any[];
      groups: any[];
      integrationKnowledgeList: any[];
    };
    removeAttachment: { file: { id: string } };
  }>();
</script>

<Settings.Group title={m.flow_step_section_context()}>
  {#if assistantLoading}
    <div class="text-secondary flex items-center gap-2 px-4 py-3 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_step_assistant_loading()}
    </div>
  {:else if assistant}
    {@const currentAssistant = assistant}
    <div
      class="border-accent-default/15 bg-accent-dimmer/50 mb-4 rounded-xl border px-4 py-3"
    >
      <p class="text-accent-stronger text-sm font-medium">
        {m.flow_step_context_runtime_files_title()}
      </p>
      <p class="text-accent-stronger/90 mt-1 text-xs leading-relaxed">
        {m.flow_step_context_runtime_files_body()}
      </p>
    </div>
    <Settings.Row title={m.knowledge()} description={m.flow_step_knowledge_desc()}>
      <SelectKnowledgeV2
        originMode="personal"
        bind:selectedWebsites={currentAssistant.websites}
        bind:selectedCollections={currentAssistant.groups}
        bind:selectedIntegrationKnowledge={currentAssistant.integration_knowledge_list}
        on:change={() => {
          dispatch("knowledgeChange", {
            websites: currentAssistant.websites,
            groups: currentAssistant.groups,
            integrationKnowledgeList: currentAssistant.integration_knowledge_list
          });
        }}
      />
      <SelectKnowledgeV2
        originMode="organization"
        bind:selectedWebsites={currentAssistant.websites}
        bind:selectedCollections={currentAssistant.groups}
        bind:selectedIntegrationKnowledge={currentAssistant.integration_knowledge_list}
        on:change={() => {
          dispatch("knowledgeChange", {
            websites: currentAssistant.websites,
            groups: currentAssistant.groups,
            integrationKnowledgeList: currentAssistant.integration_knowledge_list
          });
        }}
      />
    </Settings.Row>
    <Settings.Row title={m.attachments()} description={m.flow_step_attachments_desc()}>
      <div class="w-full">
        {#each Array.isArray(assistant.attachments) ? assistant.attachments : [] as file (file.id)}
          <div
            class="border-default bg-primary hover:bg-hover-dimmer flex h-16 items-center gap-3 border-b px-4"
          >
            <UploadedFileIcon {file}></UploadedFileIcon>
            <div class="flex flex-grow items-center justify-between gap-1">
              <AttachmentPreview {file} isTableView={true}>
                {#snippet children({ showFile }: { showFile: () => void })}
                  <button
                    on:click={showFile}
                    class="line-clamp-1 cursor-pointer text-left hover:underline"
                  >
                    {file.name}
                  </button>
                {/snippet}
              </AttachmentPreview>
              <span class="text-secondary line-clamp-1 text-right text-sm">
                {formatFileType(file.mimetype)} · {formatBytes(file.size)}
              </span>
            </div>
            <div class="min-w-8">
              <Button
                variant="destructive"
                padding="icon"
                on:click={() => dispatch("removeAttachment", { file })}
              >
                <IconTrash></IconTrash>
              </Button>
            </div>
          </div>
        {/each}

        {#each runningUploads as upload (upload.id)}
          <div
            class="border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-4 border-b px-4"
          >
            <UploadedFileIcon file={{ mimetype: upload.file.type }}></UploadedFileIcon>
            <div class="flex flex-grow flex-col gap-1">
              <div class="flex max-w-full items-center gap-4">
                <span class="line-clamp-1 flex-grow font-medium">{upload.file.name}</span>
                <span class="text-secondary line-clamp-1 text-right text-sm">
                  {formatFileType(upload.file.type)} · {formatBytes(upload.file.size)}
                </span>
              </div>
              <div class="bg-hover-dimmer h-1.5 w-full overflow-hidden rounded-full">
                <div
                  class="bg-accent-default h-full transition-all"
                  style={`width: ${upload.progress}%`}
                ></div>
              </div>
            </div>
            <div class="min-w-8">
              <Button
                variant="destructive"
                padding="icon"
                on:click={() => upload.remove()}
              >
                <IconCancel />
              </Button>
            </div>
          </div>
        {/each}
        <div class="mt-2">
          <AttachmentUploadTextButton multiple></AttachmentUploadTextButton>
        </div>
      </div>
    </Settings.Row>
  {/if}
</Settings.Group>
