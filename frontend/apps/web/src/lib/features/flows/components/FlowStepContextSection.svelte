<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type {
    GroupSparse,
    IntegrationKnowledge,
    UploadedFile,
    WebsiteSparse
  } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconCancel } from "@eneo/icons/cancel";
  import SelectKnowledge from "$lib/features/knowledge/components/select/SelectKnowledge.svelte";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import { formatFileType } from "$lib/core/formatting/formatFileType";

  let {
    assistant,
    assistantLoading,
    runningUploads,
    isPublished = false,
    onKnowledgeChange,
    onRemoveAttachment,
    collapsible = false,
    resetKey
  }: {
    collapsible?: boolean;
    resetKey?: string | number;
    isPublished?: boolean;
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

  const hasKnowledge = $derived(
    selectedWebsites.length > 0 ||
      selectedGroups.length > 0 ||
      selectedIntegrationKnowledge.length > 0 ||
      (assistant?.attachments?.length ?? 0) > 0
  );
  const knowledgeStatus = $derived(
    hasKnowledge ? m.flow_section_status_knowledge_active() : m.flow_section_status_knowledge_none()
  );

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
    if (isPublished) return;
    onKnowledgeChange?.({
      websites: selectedWebsites,
      groups: selectedGroups,
      integrationKnowledgeList: selectedIntegrationKnowledge
    });
  });
</script>

<FlowStepSection
  title={m.flow_step_section_context()}
  {collapsible}
  {resetKey}
  status={knowledgeStatus}
>
  {#if assistantLoading}
    <div class="text-secondary flex items-center gap-2 px-4 py-3 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_step_assistant_loading()}
    </div>
  {:else if assistant}
    <Settings.Row
      title={m.knowledge()}
      description={m.flow_step_knowledge_desc()}
      density="compact"
    >
      {#if isPublished}
        <!-- Published flows are read-only: the selected knowledge stays
             visible, the pickers (mutators) do not render. -->
        {#if selectedWebsites.length + selectedGroups.length + selectedIntegrationKnowledge.length > 0}
          <ul class="text-secondary flex flex-col gap-1 text-sm">
            {#each selectedGroups as item (item.id)}
              <li class="line-clamp-1">{item.name}</li>
            {/each}
            {#each selectedWebsites as item (item.id)}
              <li class="line-clamp-1">{formatWebsiteName(item)}</li>
            {/each}
            {#each selectedIntegrationKnowledge as item (item.id)}
              <li class="line-clamp-1">{item.name}</li>
            {/each}
          </ul>
        {:else}
          <p class="text-muted text-sm">{m.flow_section_status_knowledge_none()}</p>
        {/if}
      {:else}
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
      {/if}
    </Settings.Row>
    <Settings.Row
      title={m.attachments()}
      description={m.flow_step_attachments_desc()}
      density="compact"
    >
      <div class="w-full">
        <p class="text-secondary mb-3 text-[0.8125rem] leading-relaxed">
          {m.flow_step_runtime_files_help()}
        </p>
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
            {#if !isPublished}
              <div class="min-w-8">
                <Button
                  variant="destructive"
                  size="icon"
                  aria-label={m.remove()}
                  onclick={() => onRemoveAttachment?.({ file })}
                >
                  <IconTrash></IconTrash>
                </Button>
              </div>
            {/if}
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
            {#if !isPublished}
              <div class="min-w-8">
                <Button
                  variant="destructive"
                  size="icon"
                  aria-label={m.cancel()}
                  onclick={() => upload.remove()}
                >
                  <IconCancel />
                </Button>
              </div>
            {/if}
          </div>
        {/each}
        {#if !isPublished}
          <div class="mt-2">
            <AttachmentUploadTextButton multiple></AttachmentUploadTextButton>
          </div>
        {/if}
      </div>
    </Settings.Row>
  {/if}
</FlowStepSection>
