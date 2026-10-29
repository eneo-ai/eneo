<script lang="ts">
  import { onDestroy, onMount, tick, untrack } from "svelte";
  import { useId } from "bits-ui";
  import {
    readableInstructions,
    referenceUri,
    type ReferenceCandidate,
    type ReferenceCatalog
  } from "@eneo/skill-instructions";
  import type { ReferenceSelection } from "@eneo/skill-instructions/editor";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import FileText from "@lucide/svelte/icons/file-text";
  import Plug from "@lucide/svelte/icons/plug";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { CAPABILITIES, getCapability } from "$lib/features/mcp/capabilities";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { SkillCatalogQuery } from "./skillCatalogQuery.svelte";

  let {
    catalog,
    selection,
    inline = false,
    onClose,
    onSelect,
    onRemove
  }: {
    catalog: ReferenceCatalog;
    selection: ReferenceSelection;
    inline?: boolean;
    onClose: () => void;
    onSelect: (candidate: ReferenceCandidate) => void;
    onRemove: () => void;
  } = $props();
  type Category = "skills" | "functions" | "mcp";
  const id = useId();
  const initialKind = untrack(() => selection.reference?.target.kind);
  let category = $state<Category>(
    initialKind === "function" ? "functions" : initialKind?.startsWith("mcp") ? "mcp" : "skills"
  );
  let server = $state<ReferenceCandidate | null>(null);
  let selected = $state<ReferenceCandidate | null>(null);
  let preview = $state("");
  let previewLoading = $state(false);
  let previewError = $state<string | null>(null);
  let searchInput = $state<HTMLInputElement | null>(null);
  let previewHeading = $state<HTMLHeadingElement | null>(null);
  let connectionItems: { key: string; items: ReferenceCandidate[] } | null = null;
  let previewRequest: AbortController | null = null;
  const lifetime = new AbortController();
  const query = new SkillCatalogQuery<ReferenceCandidate & { id: string }>(
    { items: [] },
    async ({ query: search, cursor, limit }) => {
      if (category === "skills") {
        const page = await catalog.skills(search ?? "", cursor ?? null, lifetime.signal);
        return {
          items: page.items.map((item) => ({ ...item, id: referenceUri(item.target) })),
          next_cursor: page.nextCursor
        };
      }
      let items: ReferenceCandidate[];
      if (category === "functions")
        items = CAPABILITIES.map(({ purpose, label, bundledSummary }) => ({
          label: label(),
          description: bundledSummary?.() ?? "",
          target: { kind: "function", purpose }
        }));
      else {
        const key = server?.target.kind === "mcp_server" ? server.target.server_id : "connections";
        if (connectionItems?.key === key) items = connectionItems.items;
        else {
          items =
            key === "connections"
              ? await catalog.servers(lifetime.signal)
              : await catalog.tools(key, lifetime.signal);
          connectionItems = { key, items };
        }
      }
      const filtered = items.filter((item) =>
        `${item.label} ${item.description}`
          .toLocaleLowerCase()
          .includes((search ?? "").toLocaleLowerCase())
      );
      const offset = cursor ? Number(cursor) : 0;
      return {
        items: filtered
          .slice(offset, offset + limit)
          .map((item) => ({ ...item, id: referenceUri(item.target) })),
        next_cursor: offset + limit < filtered.length ? String(offset + limit) : null
      };
    }
  );

  onMount(() => {
    void query.reload();
    searchInput?.focus();
  });
  onDestroy(() => {
    query.dispose();
    lifetime.abort();
    previewRequest?.abort();
  });

  function changeCategory(next: Category, nextServer: ReferenceCandidate | null = null) {
    category = next;
    server = nextServer;
    selected = null;
    connectionItems = null;
    previewRequest?.abort();
    previewLoading = false;
    previewError = null;
    query.reset({ items: [] });
    void query.reload();
    searchInput?.focus();
  }

  function back() {
    previewRequest?.abort();
    selected = null;
    previewError = null;
    previewLoading = false;
    requestAnimationFrame(() => searchInput?.focus());
  }

  async function select(item: ReferenceCandidate) {
    if (item.target.kind === "function" || item.target.kind === "mcp_tool") {
      onSelect(item);
      return;
    }
    previewRequest?.abort();
    selected = item;
    preview = "";
    previewError = null;
    previewLoading = item.target.kind === "skill";
    await tick();
    previewHeading?.focus();
    if (!previewLoading) return;
    const request = new AbortController();
    previewRequest = request;
    try {
      const text = await catalog.preview(item, request.signal);
      if (!request.signal.aborted) preview = text;
    } catch (error) {
      if (!request.signal.aborted) previewError = getErrorMessage(error);
    } finally {
      if (!request.signal.aborted) previewLoading = false;
    }
  }
</script>

{#snippet content()}
  {#if selected}
    <div class="border-border flex shrink-0 flex-col gap-3 border-b px-4 pt-3 pb-4">
      <Button type="button" variant="ghost" size="sm" class="mr-auto" onclick={back}>
        <ArrowLeft data-icon="inline-start" />{m.skills_reference_back()}
      </Button>
      <div class="flex flex-wrap items-center gap-2">
        <h3
          bind:this={previewHeading}
          tabindex="-1"
          id={`${id}-preview`}
          class="min-w-0 text-base font-semibold wrap-anywhere outline-none"
        >
          {selected.label}
        </h3>
        {#if selected.revisionNumber !== undefined}<Badge variant="secondary"
            >{m.organization_skills_version({ version: String(selected.revisionNumber) })}</Badge
          >{/if}
      </div>
    </div>
  {/if}
  <div class="flex min-h-0 flex-col gap-3 overflow-x-hidden overflow-y-auto overscroll-contain p-4">
    {#if selected}
      <section aria-labelledby={`${id}-preview`} class="flex min-w-0 flex-col gap-3">
        {#if selected.description}
          {#if selected.target.kind === "skill"}
            <details class="text-sm">
              <summary class="cursor-pointer py-1 font-medium"
                >{m.skills_description_label()}</summary
              >
              <p class="mt-2 leading-relaxed whitespace-pre-wrap wrap-anywhere">
                {selected.description}
              </p>
            </details>
          {:else}<p class="text-sm leading-relaxed whitespace-pre-wrap wrap-anywhere">
              {selected.description}
            </p>{/if}
        {/if}
        <p class="text-muted-foreground text-sm leading-relaxed">
          {selected.target.kind === "skill"
            ? m.skills_reference_fixed_version()
            : m.skills_reference_tools_hint()}
        </p>
        {#if selected.target.kind === "skill"}
          <h4 class="text-sm font-medium">{m.skills_instructions_label()}</h4>
          {#if previewLoading}<p role="status">{m.loading()}</p>
          {:else if previewError}<div role="alert">
              <p>{m.skills_reference_preview_failed()}</p>
              <p class="text-destructive">{previewError}</p>
              <Button type="button" onclick={() => selected && select(selected)}>{m.retry()}</Button
              >
            </div>
          {:else}<div
              class="border-border border-b pb-4 text-base leading-7 whitespace-pre-wrap wrap-anywhere"
            >
              {readableInstructions(preview)}
            </div>{/if}
        {:else}
          {#if selected.enabled === false}<p class="text-muted-foreground text-sm">
              {m.skills_reference_off()}
            </p>{/if}
          <Button type="button" variant="outline" onclick={() => changeCategory("mcp", selected)}
            >{m.skills_reference_tools()}<ChevronRight data-icon="inline-end" /></Button
          >
        {/if}
        <details class="text-muted-foreground text-xs">
          <summary class="cursor-pointer py-1">{m.skills_reference_details()}</summary><code
            class="break-all">{referenceUri(selected.target)}</code
          >
        </details>
      </section>
    {:else}
      <Tabs.Root value={category} onValueChange={(value) => changeCategory(value as Category)}>
        <Tabs.List variant="line" class="min-h-11 w-full" aria-label={m.skills_reference_insert()}>
          <Tabs.Trigger value="skills">{m.skills()}</Tabs.Trigger>
          <Tabs.Trigger value="functions">{m.skills_reference_functions()}</Tabs.Trigger>
          <Tabs.Trigger value="mcp">{m.skills_reference_mcps()}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value={category} class="mt-1 flex min-h-0 flex-col gap-3">
          {#if server}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              class="mr-auto"
              onclick={() => changeCategory("mcp")}
              ><ArrowLeft data-icon="inline-start" />{server.label}</Button
            >
          {/if}
          <Command.Root label={m.skills_reference_search()} shouldFilter={false}>
            <Command.Input
              name="reference-search"
              autocomplete="off"
              variant="field"
              bind:ref={searchInput}
              value={query.query}
              aria-label={m.skills_reference_search()}
              aria-controls={`${id}-results`}
              placeholder={m.skills_reference_search()}
              oninput={(event) => {
                query.setQuery(event.currentTarget.value);
                previewRequest?.abort();
              }}
            />
            <Command.List
              id={`${id}-results`}
              class="max-h-64"
              aria-label={m.skills_reference_insert()}
              aria-busy={query.loading || query.loadingMore}
            >
              {#if query.error}
                <div class="flex flex-col gap-2 p-3">
                  <p class="text-destructive" role="alert">{query.error}</p>
                  <Button type="button" onclick={() => query.retry()}>{m.retry()}</Button>
                </div>
              {:else if query.loading}
                <p class="text-muted-foreground p-4 text-sm" role="status">{m.loading()}</p>
              {:else if query.items.length === 0}
                <p class="text-muted-foreground p-4 text-sm" role="status">
                  {m.skills_reference_empty()}
                </p>
              {:else}
                <Command.Group>
                  {#each query.items as item (item.id)}
                    {@const Icon =
                      item.target.kind === "function"
                        ? getCapability(item.target.purpose)!.icon
                        : item.target.kind === "skill"
                          ? FileText
                          : Plug}
                    <Command.Item
                      value={item.id}
                      onSelect={() => select(item)}
                      class="data-selected:bg-accent min-h-11 gap-3 px-2 py-2"
                    >
                      <Icon aria-hidden="true" class="text-muted-foreground" />
                      <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span class="line-clamp-2 font-medium wrap-anywhere">{item.label}</span>
                        {#if item.description}<span
                            class="text-muted-foreground line-clamp-2 text-xs leading-5 wrap-anywhere"
                            >{item.description}</span
                          >{/if}
                        {#if item.enabled === false}<span class="text-muted-foreground text-xs"
                            >{m.skills_reference_off()}</span
                          >{/if}
                      </div>
                      {#if item.revisionNumber !== undefined}<span
                          class="text-muted-foreground shrink-0 text-xs"
                          >{m.skills_reference_version_short({
                            version: item.revisionNumber
                          })}</span
                        >{/if}
                      {#if item.target.kind === "skill" || item.target.kind === "mcp_server"}<ChevronRight
                          aria-hidden="true"
                          class="text-muted-foreground"
                        />{/if}
                    </Command.Item>
                  {/each}
                </Command.Group>
              {/if}
            </Command.List>
          </Command.Root>
          {#if query.hasMore}<Button
              type="button"
              variant="ghost"
              size="sm"
              onclick={() => query.loadMore()}
              aria-busy={query.loadingMore}
              >{query.loadingMore ? m.loading() : m.load_more()}</Button
            >{/if}
          <p class="text-muted-foreground text-xs leading-5">
            {category === "skills" ? m.skills_reference_scope() : m.skills_reference_tools_hint()}
          </p>
        </Tabs.Content>
      </Tabs.Root>
    {/if}
  </div>
  <div class="border-border flex shrink-0 flex-wrap justify-end gap-2 border-t p-3">
    {#if selection.reference}<Button
        type="button"
        variant="ghost"
        class="mr-auto"
        onclick={onRemove}>{m.skills_reference_remove()}</Button
      >{/if}
    <Button type="button" variant="outline" onclick={onClose}>{m.cancel()}</Button>
    {#if selected}<Button
        type="button"
        disabled={previewLoading || !!previewError}
        onclick={() => selected && onSelect(selected)}
        >{selected.target.kind === "mcp_server"
          ? m.skills_reference_whole_mcp()
          : m.skills_reference_insert()}</Button
      >{/if}
  </div>
{/snippet}

{#if inline}
  <section
    class="border-border bg-popover text-popover-foreground pointer-coarse:[&_button]:min-h-[44px] pointer-coarse:[&_button]:min-w-[44px] pointer-coarse:[&_[role=tab]]:min-h-[44px] flex max-h-[min(36rem,75dvh)] min-h-0 flex-col overflow-hidden rounded-xl border"
    aria-label={m.skills_reference_insert()}
  >
    <h3 class="px-4 pt-4 font-semibold">
      {selection.reference ? m.skills_reference_edit() : m.skills_reference_insert()}
    </h3>
    {@render content()}
  </section>
{:else}
  <Dialog.Root
    open
    onOpenChange={(open) => {
      if (!open) onClose();
    }}
  >
    <Dialog.Content
      class={[
        "pointer-coarse:[&_button]:min-h-[44px] pointer-coarse:[&_button]:min-w-[44px] pointer-coarse:[&_[role=tab]]:min-h-[44px] flex min-h-0 flex-col gap-0 overflow-hidden p-0",
        selected?.target.kind === "skill"
          ? "max-h-[min(48rem,calc(100dvh-4rem))] sm:max-w-2xl"
          : "max-h-[min(36rem,calc(100dvh-2rem))] sm:max-w-lg"
      ]}
      closeLabel={m.cancel()}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        searchInput?.focus();
      }}
      onCloseAutoFocus={(event) => event.preventDefault()}
    >
      <Dialog.Header class="shrink-0 px-4 pt-4 pr-12"
        ><Dialog.Title
          >{selection.reference
            ? m.skills_reference_edit()
            : m.skills_reference_insert()}</Dialog.Title
        ><Dialog.Description class="sr-only">{m.skills_reference_review()}</Dialog.Description
        ></Dialog.Header
      >
      {@render content()}
    </Dialog.Content>
  </Dialog.Root>
{/if}
