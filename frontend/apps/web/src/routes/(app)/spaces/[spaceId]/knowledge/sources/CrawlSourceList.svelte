<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "@intric/ui";
  import { Pencil, Plus, Trash2 } from "lucide-svelte";

  export type CrawlSourceRow = {
    id: string;
    url: string;
    crawlType: "crawl" | "sitemap";
    depth: number;
    httpAuthUser: string | null;
    createdAt: string;
  };

  type Props = {
    rows: CrawlSourceRow[];
    loading: boolean;
    error: string | null;
    deletingId: string | null;
    onAdd: () => void;
    onEdit: (row: CrawlSourceRow) => void;
    onDelete: (row: CrawlSourceRow) => void;
  };

  let { rows, loading, error, deletingId, onAdd, onEdit, onDelete }: Props = $props();

  function crawlTypeLabel(type: "crawl" | "sitemap"): string {
    return type === "sitemap" ? "Sitemap" : "Länkdjup";
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center justify-between">
    <span class="text-default text-sm font-medium">Crawl-källor</span>
    <Button variant="outlined" size="sm" onclick={onAdd}>
      <Plus class="mr-1 h-4 w-4" />
      Lägg till crawl-källa
    </Button>
  </div>

  {#if error}
    <div
      class="border-negative-default/30 bg-negative-dimmer text-negative-stronger rounded-md border px-3 py-2 text-sm"
      role="alert"
    >
      {error}
    </div>
  {/if}

  {#if loading && rows.length === 0}
    <p class="text-muted text-sm">Hämtar crawl-källor…</p>
  {:else if rows.length === 0}
    <p class="text-muted text-sm">
      Inga crawl-källor än. Lägg till en URL för att hämta innehåll från webben automatiskt.
    </p>
  {:else}
    <ul class="border-default divide-default bg-primary divide-y rounded-md border">
      {#each rows as row (row.id)}
        <li class="flex items-start justify-between gap-3 px-3 py-2">
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <span class="truncate text-sm font-medium" title={row.url}>{row.url}</span>
            <span class="text-muted flex flex-wrap items-center gap-x-3 text-xs">
              <span>{crawlTypeLabel(row.crawlType)}</span>
              <span>Djup {row.depth}</span>
              {#if row.httpAuthUser}
                <span title="HTTP Basic-autentisering aktiverad">Auth: {row.httpAuthUser}</span>
              {/if}
            </span>
          </div>
          <Button
            variant="outlined"
            size="sm"
            onclick={() => onEdit(row)}
            aria-label="Redigera crawl-källan {row.url}"
          >
            <Pencil class="h-4 w-4" />
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={deletingId === row.id}
            onclick={() => onDelete(row)}
            aria-label="Ta bort crawl-källan {row.url}"
          >
            <Trash2 class="h-4 w-4" />
          </Button>
        </li>
      {/each}
    </ul>
  {/if}
</div>
