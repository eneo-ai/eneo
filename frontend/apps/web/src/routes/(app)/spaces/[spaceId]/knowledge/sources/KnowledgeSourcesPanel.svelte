<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { Button, Dialog } from "@intric/ui";
  import { ChevronRight, Plus, RefreshCw, Trash2, Upload } from "lucide-svelte";
  import { onDestroy, onMount, untrack } from "svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { writable } from "svelte/store";

  type SpaceMCPServer = {
    id: string;
    name: string;
    description?: string | null;
    http_url: string;
    http_auth_type: string;
    has_credentials?: boolean;
    tags?: string[] | null;
  };

  type KnowledgeSourceRow = {
    id: string;
    eneo_knowledge_slug: string;
    mcp_server_id: string;
    name: string;
  };

  type KnowledgeFile = {
    id: string;
    name: string;
    mime_type: string;
    size_bytes: number;
    status: string;
    error?: string | null;
    page_count?: number | null;
    created_at: string;
    processed_at?: string | null;
  };

  const intric = getIntric();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  let spaceId = $derived($currentSpace.id);

  let servers = $state<SpaceMCPServer[]>([]);
  let knowledgeSources = $state<KnowledgeSourceRow[]>([]);
  let loadingList = $state(true);
  let listError = $state<string | null>(null);

  const knowledgeSourceByMcp = $derived(
    new Map(knowledgeSources.map((ks) => [ks.mcp_server_id, ks]))
  );

  async function refreshList() {
    loadingList = true;
    listError = null;
    try {
      const [serverList, ksList] = await Promise.all([
        intric.mcpServers.listForSpace({ space_id: spaceId }),
        intric.mcpServers.listSpaceKnowledgeSources({ space_id: spaceId })
      ]);
      servers = serverList as SpaceMCPServer[];
      const nameById = new Map(serverList.map((s) => [s.id, s.name]));
      knowledgeSources = ksList.map((ks) => ({
        id: ks.id,
        eneo_knowledge_slug: ks.eneo_knowledge_slug,
        mcp_server_id: ks.mcp_server_id,
        name: nameById.get(ks.mcp_server_id) ?? ks.eneo_knowledge_slug
      }));
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      listError = e?.message ?? e?.body?.message ?? "Kunde inte hämta kunskapskällor.";
    } finally {
      loadingList = false;
    }
  }

  onMount(() => {
    refreshList();
  });

  const showAddDialog = writable(false);
  let newName = $state("");
  let submitting = $state(false);
  let errorMessage = $state("");
  let deletingId = $state<string | null>(null);
  const refreshingTools = new SvelteSet<string>();

  const expanded = new SvelteSet<string>();
  const filesByMcp = new SvelteMap<string, KnowledgeFile[]>();
  const filesLoading = new SvelteSet<string>();
  const fileError = new SvelteMap<string, string>();
  const uploadingByMcp = new SvelteSet<string>();
  const deletingFile = new SvelteSet<string>();

  $effect(() => {
    if (!$showAddDialog) {
      newName = "";
      errorMessage = "";
    }
  });

  async function handleCreate() {
    if (!newName.trim()) return;
    submitting = true;
    errorMessage = "";
    try {
      await intric.mcpServers.createKnowledgeSource({ space_id: spaceId, name: newName });
      $showAddDialog = false;
      newName = "";
      await Promise.all([refreshList(), invalidate("spaces:data")]);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      errorMessage = e?.message ?? e?.body?.message ?? "Det gick inte att skapa kunskapskällan.";
    } finally {
      submitting = false;
    }
  }

  async function handleRefreshTools(server: SpaceMCPServer) {
    refreshingTools.add(server.id);
    try {
      const result = await intric.mcpServers.refreshSpaceMcpServerTools({
        space_id: spaceId,
        mcp_server_id: server.id
      });
      const count = (result as { tools_discovered?: number })?.tools_discovered ?? 0;
      alert(`Verktygsdefinitioner uppdaterade (${count} verktyg).`);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      alert(e?.message ?? e?.body?.message ?? "Det gick inte att uppdatera verktygen.");
    } finally {
      refreshingTools.delete(server.id);
    }
  }

  async function handleDeleteSource(server: SpaceMCPServer) {
    if (!confirm(`Ta bort kunskapskällan "${server.name}"?`)) return;
    deletingId = server.id;
    try {
      await intric.mcpServers.deleteFromSpace({ space_id: spaceId, id: server.id });
      await Promise.all([refreshList(), invalidate("spaces:data")]);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      alert(e?.message ?? e?.body?.message ?? "Det gick inte att ta bort kunskapskällan.");
    } finally {
      deletingId = null;
    }
  }

  async function loadFiles(mcpServerId: string) {
    const ks = knowledgeSourceByMcp.get(mcpServerId);
    if (!ks) return;
    filesLoading.add(mcpServerId);
    fileError.delete(mcpServerId);
    try {
      const list = (await intric.mcpServers.listKnowledgeSourceFiles({
        space_id: spaceId,
        knowledge_source_id: ks.id
      })) as KnowledgeFile[];
      filesByMcp.set(mcpServerId, list);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      fileError.set(mcpServerId, e?.message ?? e?.body?.message ?? "Kunde inte hämta filer.");
    } finally {
      filesLoading.delete(mcpServerId);
    }
  }

  async function toggleExpanded(mcpServerId: string) {
    if (expanded.has(mcpServerId)) {
      expanded.delete(mcpServerId);
      return;
    }
    expanded.add(mcpServerId);
    if (!filesByMcp.has(mcpServerId)) {
      await loadFiles(mcpServerId);
    }
  }

  async function handleUpload(server: SpaceMCPServer, fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const ks = knowledgeSourceByMcp.get(server.id);
    if (!ks) {
      alert(
        "Kan inte ladda upp filer till denna MCP-server — den hanteras inte som en kunskapskälla."
      );
      return;
    }
    uploadingByMcp.add(server.id);
    fileError.delete(server.id);
    try {
      for (const file of Array.from(fileList)) {
        await intric.mcpServers.uploadKnowledgeSourceFile({
          space_id: spaceId,
          knowledge_source_id: ks.id,
          file
        });
      }
      await loadFiles(server.id);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      fileError.set(
        server.id,
        e?.message ?? e?.body?.message ?? "Det gick inte att ladda upp filen."
      );
    } finally {
      uploadingByMcp.delete(server.id);
    }
  }

  async function handleDeleteFile(server: SpaceMCPServer, file: KnowledgeFile) {
    const ks = knowledgeSourceByMcp.get(server.id);
    if (!ks) return;
    if (!confirm(`Ta bort filen "${file.name}"?`)) return;
    deletingFile.add(file.id);
    try {
      await intric.mcpServers.deleteKnowledgeSourceFile({
        space_id: spaceId,
        knowledge_source_id: ks.id,
        file_id: file.id
      });
      await loadFiles(server.id);
    } catch (err) {
      const e = err as { message?: string; body?: { message?: string } };
      alert(e?.message ?? e?.body?.message ?? "Det gick inte att ta bort filen.");
    } finally {
      deletingFile.delete(file.id);
    }
  }

  // Poll every 4s for files in queued/processing state on any expanded server.
  let pollHandle: ReturnType<typeof setInterval> | undefined;
  $effect(() => {
    const anyPending = Array.from(expanded).some((mcpServerId) => {
      const files = filesByMcp.get(mcpServerId) ?? [];
      return files.some((f) => f.status === "queued" || f.status === "processing");
    });
    if (anyPending && !pollHandle) {
      pollHandle = setInterval(() => {
        const targets = untrack(() => Array.from(expanded));
        for (const mcpServerId of targets) {
          const files = untrack(() => filesByMcp.get(mcpServerId) ?? []);
          if (files.some((f) => f.status === "queued" || f.status === "processing")) {
            loadFiles(mcpServerId);
          }
        }
      }, 4000);
    } else if (!anyPending && pollHandle) {
      clearInterval(pollHandle);
      pollHandle = undefined;
    }
  });

  onDestroy(() => {
    if (pollHandle) clearInterval(pollHandle);
  });

  function statusLabel(status: string): string {
    switch (status) {
      case "queued":
        return "I kö";
      case "processing":
        return "Bearbetas";
      case "ready":
        return "Klar";
      case "failed":
        return "Misslyckades";
      default:
        return status;
    }
  }

  function statusClass(status: string): string {
    switch (status) {
      case "ready":
        return "bg-positive-dimmer text-positive-stronger";
      case "failed":
        return "bg-negative-dimmer text-negative-stronger";
      case "queued":
      case "processing":
        return "bg-label-dimmer text-label-stronger";
      default:
        return "bg-secondary text-muted";
    }
  }

  function humanSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
</script>

<div class="flex flex-col gap-4 py-4 pr-6">
  <div class="flex items-start justify-between gap-6">
    <p class="text-muted max-w-prose text-sm">
      Lägg till kunskapskällor som lever i eneo-knowledge. De dyker upp som vanliga MCP-servrar för
      assistenterna i utrymmet — välj dem under "MCP-servrar" på en assistent och börja ladda upp
      filer för att fylla på källan.
    </p>
    <Button
      variant="primary"
      onclick={() => ($showAddDialog = true)}
      class="shrink-0 whitespace-nowrap"
    >
      <Plus class="mr-2 h-4 w-4" />
      Lägg till kunskapskälla
    </Button>
  </div>

  {#if listError}
    <div
      class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-md border px-3 py-2 text-sm"
      role="alert"
    >
      {listError}
    </div>
  {/if}

  {#if loadingList && servers.length === 0}
    <p class="text-muted text-sm">Hämtar kunskapskällor…</p>
  {:else if servers.length === 0}
    <div
      class="border-dimmer bg-secondary/30 flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center"
    >
      <p class="text-default text-sm font-medium">Inga kunskapskällor än</p>
      <p class="text-muted max-w-prose text-sm">
        Klicka på "Lägg till kunskapskälla" för att skapa den första. Den kopplas automatiskt till
        detta utrymme.
      </p>
    </div>
  {:else}
    <ul
      class="border-default divide-default divide-y rounded-lg border"
      aria-label="Kunskapskällor"
    >
      {#each servers as server (server.id)}
        {@const isExpanded = expanded.has(server.id)}
        {@const isManaged = knowledgeSourceByMcp.has(server.id)}
        {@const files = filesByMcp.get(server.id) ?? []}
        <li class="flex flex-col">
          <div class="flex items-start justify-between gap-3 px-2 py-3">
            <button
              type="button"
              class="hover:bg-hover-dimmer flex flex-1 items-start gap-2 rounded-md p-2 text-left"
              onclick={() => toggleExpanded(server.id)}
              aria-expanded={isExpanded}
              aria-label="Visa filer för {server.name}"
            >
              <ChevronRight
                class="mt-0.5 h-4 w-4 transition-transform {isExpanded ? 'rotate-90' : ''}"
              />
              <span class="flex flex-1 flex-col gap-1">
                <span class="font-medium">{server.name}</span>
                {#if server.description}
                  <span class="text-muted text-sm">{server.description}</span>
                {/if}
              </span>
            </button>
            {#if isManaged}
              <Button
                variant="outlined"
                size="sm"
                disabled={refreshingTools.has(server.id)}
                onclick={() => handleRefreshTools(server)}
                aria-label="Uppdatera verktygsdefinitioner för {server.name}"
              >
                <RefreshCw class="h-4 w-4 {refreshingTools.has(server.id) ? 'animate-spin' : ''}" />
              </Button>
            {/if}
            <Button
              variant="destructive"
              size="sm"
              disabled={deletingId === server.id}
              onclick={() => handleDeleteSource(server)}
              aria-label="Ta bort {server.name}"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
          </div>

          {#if isExpanded}
            <div class="border-default bg-secondary/30 border-t px-4 py-3">
              {#if !isManaged}
                <p class="text-muted text-sm">
                  Filuppladdning är bara tillgänglig för kunskapskällor som skapats via "Lägg till
                  kunskapskälla".
                </p>
              {:else}
                <div class="flex items-center justify-between gap-3 pb-3">
                  <span class="text-default text-sm font-medium">Filer</span>
                  <label class="inline-flex items-center">
                    <input
                      type="file"
                      multiple
                      class="hidden"
                      accept=".pdf,.docx,.md,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/plain"
                      disabled={uploadingByMcp.has(server.id)}
                      onchange={(e) => {
                        const target = e.currentTarget as HTMLInputElement;
                        handleUpload(server, target.files);
                        target.value = "";
                      }}
                    />
                    <span
                      class="border-default bg-primary ring-accent-default hover:bg-hover-dimmer inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium shadow-sm"
                      class:opacity-50={uploadingByMcp.has(server.id)}
                    >
                      <Upload class="h-4 w-4" />
                      {uploadingByMcp.has(server.id) ? m.loading() : "Lägg till fil"}
                    </span>
                  </label>
                </div>

                {#if fileError.has(server.id)}
                  <div
                    class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mb-3 rounded-md border px-3 py-2 text-sm"
                    role="alert"
                  >
                    {fileError.get(server.id)}
                  </div>
                {/if}

                {#if filesLoading.has(server.id) && files.length === 0}
                  <p class="text-muted text-sm">Hämtar filer…</p>
                {:else if files.length === 0}
                  <p class="text-muted text-sm">
                    Inga filer än. Ladda upp PDF, DOCX, MD eller TXT för att börja.
                  </p>
                {:else}
                  <ul class="border-default divide-default bg-primary divide-y rounded-md border">
                    {#each files as file (file.id)}
                      <li class="flex items-start justify-between gap-3 px-3 py-2">
                        <div class="flex min-w-0 flex-1 flex-col gap-1">
                          <span class="truncate text-sm font-medium">{file.name}</span>
                          <span class="text-muted text-xs">
                            {humanSize(file.size_bytes)}
                            {#if file.page_count}
                              · {file.page_count} sidor
                            {/if}
                          </span>
                          {#if file.status === "failed" && file.error}
                            <span class="text-negative-stronger text-xs">{file.error}</span>
                          {/if}
                        </div>
                        <span
                          class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {statusClass(
                            file.status
                          )}"
                        >
                          {statusLabel(file.status)}
                        </span>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={deletingFile.has(file.id)}
                          onclick={() => handleDeleteFile(server, file)}
                          aria-label="Ta bort {file.name}"
                        >
                          <Trash2 class="h-4 w-4" />
                        </Button>
                      </li>
                    {/each}
                  </ul>
                {/if}
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<Dialog.Root openController={showAddDialog}>
  <Dialog.Content width="medium">
    <Dialog.Title>Lägg till kunskapskälla</Dialog.Title>
    <Dialog.Section scrollable={true}>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          handleCreate();
        }}
        class="space-y-4 px-4 pt-2 pb-6"
      >
        {#if errorMessage}
          <div
            class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-lg border px-4 py-3 text-sm"
            role="alert"
          >
            {errorMessage}
          </div>
        {/if}

        <p class="text-muted text-sm">
          Ge kunskapskällan ett namn. Den skapas direkt i eneo-knowledge och kopplas till detta
          utrymme. Assistenter i utrymmet får tillgång till den automatiskt.
        </p>

        <div>
          <label for="knowledge-source-name" class="text-default mb-1.5 block text-sm font-medium">
            {m.name()}
            <span class="text-negative-default" aria-hidden="true">*</span>
          </label>
          <input
            id="knowledge-source-name"
            type="text"
            bind:value={newName}
            required
            placeholder="T.ex. Handboken"
            autocomplete="off"
            class="border-default bg-primary ring-accent-default focus:border-accent-default w-full rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:ring-2 focus:outline-none"
          />
        </div>
      </form>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined" disabled={submitting}>{m.cancel()}</Button>
      <Button variant="primary" onclick={handleCreate} disabled={submitting || !newName.trim()}>
        {submitting ? m.loading() : "Skapa"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
