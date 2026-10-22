<script lang="ts">
  import { untrack } from "svelte";
  import type { WebsiteContentFolder } from "@eneo/eneo-js";
  import Folder from "@lucide/svelte/icons/folder";
  import { getEneo } from "$lib/core/Eneo";
  import SourceTreeNav, {
    type SourceTreeRow
  } from "$lib/features/knowledge/components/SourceTreeNav.svelte";
  import { m } from "$lib/paraglide/messages";

  let {
    websiteId,
    revision,
    total,
    selectedPrefix,
    hrefFor,
    onselect
  }: {
    websiteId: string;
    /** The crawl whose indexed snapshot the counts describe; a new snapshot reloads them. */
    revision: string | undefined;
    total: number;
    selectedPrefix: string;
    hrefFor: (prefix: string | null) => string;
    onselect: (prefix: string | null) => void;
  } = $props();

  interface Branch {
    items: WebsiteContentFolder[];
    cursor: string | null;
    loading: boolean;
    failed: boolean;
  }
  interface Row extends SourceTreeRow {
    count?: number;
  }
  const eneo = getEneo();
  let branches = $state<Record<string, Branch>>({});
  let expanded = $state<Record<string, boolean>>({});
  let generation = 0;

  async function load(prefix: string, more = false) {
    if (branches[prefix]?.loading) return;
    const request = generation;
    const previous = branches[prefix];
    branches[prefix] = {
      items: previous?.items ?? [],
      cursor: previous?.cursor ?? null,
      loading: true,
      failed: false
    };
    try {
      const result = await eneo.websites.indexedBlobs.folders({
        id: websiteId,
        prefix,
        cursor: more ? previous?.cursor : undefined,
        limit: 100
      });
      if (request !== generation) return;
      const known = new Set(more ? previous?.items.map((item) => item.path) : []);
      branches[prefix] = {
        items: [
          ...(more ? (previous?.items ?? []) : []),
          ...result.items.filter((item) => !known.has(item.path))
        ],
        cursor: result.next_cursor,
        loading: false,
        failed: false
      };
      if (prefix === "" && result.items.length === 1 && result.items[0].has_children) {
        const root = result.items[0].path;
        expanded[root] = true;
        if (!branches[root]) void load(root);
      }
      revealSelection();
    } catch {
      if (request === generation)
        branches[prefix] = { ...branches[prefix], loading: false, failed: true };
    }
  }

  $effect(() => {
    void websiteId;
    void revision;
    untrack(() => {
      generation += 1;
      branches = {};
      expanded = {};
      void load("");
    });
    return () => {
      generation += 1;
    };
  });

  // Reveal a deep-linked selection one existing branch at a time. Never fetch
  // the whole tree merely to locate a prefix, and keep pagination available.
  function revealSelection() {
    for (const branch of Object.values(branches)) {
      for (const item of branch.items) {
        if (
          item.has_children &&
          selectedPrefix !== item.path &&
          selectedPrefix.startsWith(item.path)
        ) {
          expanded[item.path] = true;
          if (!branches[item.path]) void load(item.path);
        }
      }
    }
  }

  $effect(() => {
    void selectedPrefix;
    untrack(revealSelection);
  });

  function label(path: string, parent: string) {
    const name = parent
      ? path.slice(parent.length, -1)
      : path.replace(/^https?:\/\//, "").replace(/\/$/, "");
    try {
      return decodeURIComponent(name);
    } catch {
      return name;
    }
  }

  function rowsFor(prefix: string, depth: number): Row[] {
    const branch = branches[prefix];
    const rows: Row[] = [];
    for (const item of branch?.items ?? []) {
      rows.push({
        id: item.path,
        name: label(item.path, prefix),
        title: item.path,
        count: item.count,
        depth,
        hasChildren: item.has_children,
        expanded: !!expanded[item.path]
      });
      if (expanded[item.path]) rows.push(...rowsFor(item.path, depth + 1));
    }
    if (!branch || branch.loading || branch.failed || branch.cursor) {
      const loading = !branch || branch.loading;
      rows.push({
        id: `control:${prefix}`,
        name: loading ? m.loading() : branch.failed ? m.source_tree_retry() : m.source_tree_more(),
        depth,
        hasChildren: false,
        expanded: false,
        disabled: loading,
        action: () => {
          void load(prefix, !!branch?.cursor);
        }
      });
    }
    return rows;
  }
  let rows = $derived(rowsFor("", 0));

  function resourceCount(count: number) {
    return count === 1
      ? m.website_source_resource_count_one({ count })
      : m.website_source_resource_count_other({ count });
  }

  function toggle(prefix: string) {
    expanded[prefix] = !expanded[prefix];
    if (expanded[prefix] && !branches[prefix]) void load(prefix);
  }
</script>

<SourceTreeNav
  title={m.website_source_structure()}
  allLabel={m.website_source_all_content()}
  {total}
  totalLabel={resourceCount(total)}
  {rows}
  emptyLabel={total === 0 ? m.website_no_indexed_content() : ""}
  selectedId={selectedPrefix || null}
  {hrefFor}
  {onselect}
  ontoggle={toggle}
  hint={m.website_source_structure_hint()}
>
  {#snippet leading()}<Folder
      class="text-secondary size-3.5 shrink-0"
      aria-hidden="true"
    />{/snippet}
  {#snippet trailing(row)}
    <span class="sr-only">, {resourceCount(row.count ?? 0)}</span>
    <span class="text-secondary text-xs tabular-nums" aria-hidden="true">{row.count}</span>
  {/snippet}
</SourceTreeNav>
