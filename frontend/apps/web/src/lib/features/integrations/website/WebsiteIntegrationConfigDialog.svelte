<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { toastError } from "$lib/core/errors";
  import { Button, Dialog, Input } from "@intric/ui";
  import type { Writable } from "svelte/store";

  type Scope = "me" | "tenant";
  type HeaderRow = { key: string; value: string };
  type Config = {
    id: string;
    name: string;
    sitemap_url: string;
    markdown_endpoint_url?: string | null;
    headers: HeaderRow[];
    sync_status: string;
    last_successful_sync_at?: string | null;
    last_sync_error?: string | null;
  };

  type Props = {
    openController: Writable<boolean>;
    scope: Scope;
    title: string;
  };

  let { openController, scope, title }: Props = $props();

  const intric = getIntric();

  let configs = $state<Config[]>([]);
  let isLoading = $state(false);
  let isSaving = $state(false);
  let editingId = $state<string | null>(null);

  let name = $state("");
  let sitemapUrl = $state("");
  let markdownEndpointUrl = $state("");
  let headersText = $state("{}");

  const basePath = $derived(`/api/v1/integrations/websites/${scope}/configs/`);

  async function loadConfigs() {
    isLoading = true;
    try {
      const response = await intric.client.fetch(basePath as any, { method: "get" } as any);
      configs = response.items ?? [];
    } catch (e) {
      toastError(e);
    }
    isLoading = false;
  }

  function resetForm() {
    editingId = null;
    name = "";
    sitemapUrl = "";
    markdownEndpointUrl = "";
    headersText = "{}";
  }

  function startEdit(config: Config) {
    editingId = config.id;
    name = config.name;
    sitemapUrl = config.sitemap_url;
    markdownEndpointUrl = config.markdown_endpoint_url ?? "";
    headersText = JSON.stringify(
      Object.fromEntries((config.headers ?? []).map((header) => [header.key, header.value])),
      null,
      2
    );
  }

  function parseHeaders(): HeaderRow[] {
    const raw = headersText.trim();
    if (raw.length === 0) return [];
    const parsed = JSON.parse(raw) as Record<string, string>;
    return Object.entries(parsed).map(([key, value]) => ({ key, value: String(value) }));
  }

  async function saveConfig() {
    isSaving = true;
    try {
      const body = {
        name,
        sitemap_url: sitemapUrl,
        markdown_endpoint_url: markdownEndpointUrl.trim() === "" ? null : markdownEndpointUrl,
        headers: parseHeaders()
      };
      if (editingId) {
        await intric.client.fetch(`${basePath}${editingId}/` as any, {
          method: "patch",
          requestBody: { "application/json": body }
        } as any);
      } else {
        await intric.client.fetch(basePath as any, {
          method: "post",
          requestBody: { "application/json": body }
        } as any);
      }
      resetForm();
      await loadConfigs();
    } catch (e) {
      toastError(e);
    }
    isSaving = false;
  }

  async function deleteConfig(id: string) {
    try {
      await intric.client.fetch(`${basePath}${id}/` as any, { method: "delete" } as any);
      if (editingId === id) {
        resetForm();
      }
      await loadConfigs();
    } catch (e) {
      toastError(e);
    }
  }

  async function pingConfig(id: string) {
    try {
      await intric.client.fetch(`/api/v1/integrations/websites/${id}/ping/` as any, {
        method: "post"
      } as any);
      await loadConfigs();
    } catch (e) {
      toastError(e);
    }
  }

  $effect(() => {
    if ($openController) {
      void loadConfigs();
    }
  });
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large">
    <Dialog.Title>{title}</Dialog.Title>

    <Dialog.Section scrollable={true}>
      <div class="grid gap-6 p-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">Configured website integrations</h3>
            <Button variant="outlined" onclick={loadConfigs} disabled={isLoading}>Refresh</Button>
          </div>

          {#if isLoading}
            <p class="text-secondary text-sm">Loading integrations...</p>
          {:else if configs.length === 0}
            <p class="text-secondary text-sm">No website integrations configured yet.</p>
          {:else}
            <div class="space-y-3">
              {#each configs as config (config.id)}
                <div class="border-default rounded-lg border p-4">
                  <div class="flex items-start justify-between gap-4">
                    <div class="min-w-0">
                      <div class="text-sm font-semibold">{config.name}</div>
                      <div class="text-secondary truncate text-xs">{config.sitemap_url}</div>
                      {#if config.markdown_endpoint_url}
                        <div class="text-secondary truncate text-xs">
                          Markdown endpoint: {config.markdown_endpoint_url}
                        </div>
                      {/if}
                    </div>
                    <div class="text-right text-xs">
                      <div class="font-medium">{config.sync_status}</div>
                      {#if config.last_successful_sync_at}
                        <div class="text-secondary">
                          {new Date(config.last_successful_sync_at).toLocaleString()}
                        </div>
                      {/if}
                    </div>
                  </div>
                  {#if config.last_sync_error}
                    <div class="text-negative-default mt-3 text-xs">{config.last_sync_error}</div>
                  {/if}
                  <div class="mt-4 flex flex-wrap gap-2">
                    <Button variant="outlined" onclick={() => startEdit(config)}>Edit</Button>
                    <Button variant="outlined" onclick={() => pingConfig(config.id)}>Ping</Button>
                    <Button variant="destructive" onclick={() => deleteConfig(config.id)}
                      >Delete</Button
                    >
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>

        <div class="border-default rounded-lg border p-4">
          <h3 class="mb-4 text-sm font-semibold">
            {editingId ? "Edit integration" : "Create integration"}
          </h3>

          <div class="space-y-4">
            <Input.Text bind:value={name} label="Name" required placeholder="Marketing sitemap" />
            <Input.Text
              bind:value={sitemapUrl}
              label="Sitemap URL"
              required
              placeholder="https://example.com/sitemap.xml"
            />
            <Input.Text
              bind:value={markdownEndpointUrl}
              label="Markdown endpoint"
              placeholder="https://example.com/markdown"
            />
            <label class="block text-sm">
              <span class="mb-1 block font-medium">Headers (JSON object)</span>
              <textarea
                bind:value={headersText}
                class="border-default bg-primary min-h-40 w-full rounded-md border px-3 py-2 font-mono text-xs"
                spellcheck="false"
              ></textarea>
            </label>
          </div>
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls>
      <Button variant="outlined" onclick={resetForm}>Clear</Button>
      <Button variant="primary" onclick={saveConfig} disabled={isSaving}>
        {isSaving ? "Saving..." : editingId ? "Save changes" : "Create integration"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
