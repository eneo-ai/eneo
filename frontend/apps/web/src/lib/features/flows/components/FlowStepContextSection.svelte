<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type {
    GroupSparse,
    IntegrationKnowledge,
    UploadedFile,
    WebsiteSparse
  } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconCancel } from "@eneo/icons/cancel";
  import SelectKnowledge from "$lib/features/knowledge/components/select/SelectKnowledge.svelte";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";

  let {
    assistant,
    assistantLoading,
    runningUploads,
    onKnowledgeChange,
    onRemoveAttachment
  }: {
    assistant: {
      id?: string;
      websites?: WebsiteSparse[];
      groups?: GroupSparse[];
      integration_knowledge_list?: IntegrationKnowledge[];
      attachments?: UploadedFile[];
    } | null;
    assistantLoading: boolean;
    runningUploads: Array<{
      id: string;
      file: File;
      status: string;
      progress: number;
      remove: () => void;
    }>;
    onKnowledgeChange?: (detail: {
      websites: WebsiteSparse[];
      groups: GroupSparse[];
      integrationKnowledgeList: IntegrationKnowledge[];
    }) => void;
    onRemoveAttachment?: (detail: { file: { id: string } }) => void;
  } = $props();

  let selectedWebsites = $state<WebsiteSparse[]>([]);
  let selectedGroups = $state<GroupSparse[]>([]);
  let selectedIntegrationKnowledge = $state<IntegrationKnowledge[]>([]);
  let lastAssistantId = $state<string | null>(null);
  let lastSourceSignature = $state("");
  let lastEmittedSignature = $state("");

  function knowledgeSignature(
    websites: WebsiteSparse[] = [],
    groups: GroupSparse[] = [],
    integrationKnowledge: IntegrationKnowledge[] = []
  ) {
    return JSON.stringify({
      websites: websites.map((item) => item.id),
      groups: groups.map((item) => item.id),
      integrationKnowledge: integrationKnowledge.map((item) => item.id)
    });
  }

  $effect(() => {
    const assistantId = assistant?.id ?? null;
    const sourceSignature = assistant
      ? knowledgeSignature(
          assistant.websites ?? [],
          assistant.groups ?? [],
          assistant.integration_knowledge_list ?? []
        )
      : "";

    if (
      assistantId !== lastAssistantId ||
      (sourceSignature !== lastSourceSignature && sourceSignature !== lastEmittedSignature)
    ) {
      lastAssistantId = assistantId;
      lastSourceSignature = sourceSignature;
      lastEmittedSignature = sourceSignature;
      selectedWebsites = assistant?.websites ?? [];
      selectedGroups = assistant?.groups ?? [];
      selectedIntegrationKnowledge = assistant?.integration_knowledge_list ?? [];
    }
  });

  $effect(() => {
    if (!assistant) return;
    const signature = knowledgeSignature(
      selectedWebsites,
      selectedGroups,
      selectedIntegrationKnowledge
    );
    if (signature === lastEmittedSignature) return;

    lastEmittedSignature = signature;
    lastSourceSignature = signature;
    onKnowledgeChange?.({
      websites: selectedWebsites,
      groups: selectedGroups,
      integrationKnowledgeList: selectedIntegrationKnowledge
    });
  });
</script>

<Settings.Group title={m.flow_step_section_context()}>
  {#if assistantLoading}
    <div class="text-secondary flex items-center gap-2 px-4 py-3 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_step_assistant_loading()}
    </div>
  {:else if assistant}
    <Alert.Root class="border-accent-default/15 bg-accent-dimmer/50 mb-4 rounded-xl" role="status">
      <Alert.Title class="text-accent-stronger text-sm font-medium">
        {m.flow_step_context_runtime_files_title()}
      </Alert.Title>
      <Alert.Description class="text-accent-stronger/90 mt-1 text-xs leading-relaxed">
        {m.flow_step_context_runtime_files_body()}
      </Alert.Description>
    </Alert.Root>
    <Settings.Row title={m.knowledge()} description={m.flow_step_knowledge_desc()}>
      <SelectKnowledge
        originMode="personal"
        bind:selectedWebsites
        bind:selectedCollections={selectedGroups}
        bind:selectedIntegrationKnowledge
      />
      <SelectKnowledge
        originMode="organization"
        bind:selectedWebsites
        bind:selectedCollections={selectedGroups}
        bind:selectedIntegrationKnowledge
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
                    onclick={showFile}
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
                size="icon"
                onclick={() => onRemoveAttachment?.({ file })}
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
              <Button variant="destructive" size="icon" onclick={() => upload.remove()}>
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
