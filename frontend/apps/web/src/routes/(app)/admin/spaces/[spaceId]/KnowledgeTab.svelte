<!--
  The knowledge sources the space owns: what kind, how big, how fresh and who
  uses them. Never document titles: even a title can hold personal data.
-->
<script lang="ts">
  import type { AdminSpaceKnowledgeSource } from "@eneo/eneo-js";
  import { Info } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatDayMedium, intlLocale } from "$lib/core/formatting/dateTime";
  import { formatList } from "$lib/core/formatting/formatList";
  import {
    knowledgeItemCount,
    knowledgeKindLabel,
    knowledgeName
  } from "$lib/features/spaces/oversight/knowledge";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    knowledge: readonly AdminSpaceKnowledgeSource[];
    /** Sources from the organisation space that the space's assistants also use. */
    inheritedCount: number;
  };

  let { knowledge, inheritedCount }: Props = $props();

  const number = new Intl.NumberFormat(intlLocale());
  const format = (value: number) => number.format(value);

  function interval(source: AdminSpaceKnowledgeSource): string | null {
    switch (source.update_interval) {
      case "daily":
        return m.admin_spaces_fetch_daily();
      case "every_other_day":
        return m.admin_spaces_fetch_every_other_day();
      case "weekly":
        return m.admin_spaces_fetch_weekly();
      case "never":
        return m.admin_spaces_fetch_never();
      default:
        return null;
    }
  }

  function extent(source: AdminSpaceKnowledgeSource): string {
    const parts = [knowledgeItemCount(source, format), formatBytes(source.size_bytes)];
    const fetched = source.kind === "website" ? interval(source) : null;
    if (fetched) parts.push(fetched);
    return parts.join(" · ");
  }

  function usedBy(source: AdminSpaceKnowledgeSource): string {
    return source.used_by.length > 0
      ? formatList(source.used_by.map((assistant) => assistant.name))
      : m.admin_spaces_not_used();
  }
</script>

<!-- The API gives the day only, so an upload's time of day is never shown. -->
{#snippet updated(source: AdminSpaceKnowledgeSource)}
  {#if source.updated_at}
    <time datetime={source.updated_at}>{formatDayMedium(source.updated_at)}</time>
  {:else}
    {m.never()}
  {/if}
{/snippet}

<section aria-labelledby="space-knowledge-title" class="flex flex-col gap-4">
  <h2 id="space-knowledge-title" class="text-lg font-semibold">
    {m.admin_spaces_knowledge_title()}
  </h2>
  <p class="text-secondary flex max-w-[75ch] items-start gap-2 text-sm">
    <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    {m.admin_spaces_knowledge_note()}
  </p>

  {#if knowledge.length > 0}
    <div class="border-default bg-primary overflow-hidden rounded-lg border">
      <Table.Root
        class="[&_td]:px-3 [&_td]:py-3 [&_td]:align-top [&_td]:whitespace-normal [&_th]:px-3 [&_th]:whitespace-normal @3xl:[&_td]:px-4 @3xl:[&_th]:px-4"
      >
        <Table.Caption class="sr-only">{m.admin_spaces_knowledge_caption()}</Table.Caption>
        <Table.Header>
          <Table.Row>
            <Table.Head scope="col">{m.admin_spaces_col_source()}</Table.Head>
            <Table.Head scope="col" class="hidden @3xl:table-cell">
              {m.admin_spaces_col_kind()}
            </Table.Head>
            <Table.Head scope="col">{m.admin_spaces_col_extent()}</Table.Head>
            <Table.Head scope="col" class="hidden @3xl:table-cell">
              {m.admin_spaces_col_updated()}
            </Table.Head>
            <Table.Head scope="col" class="hidden @5xl:table-cell">
              {m.admin_spaces_col_used_by()}
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each knowledge as source (`${source.kind}-${source.id}`)}
            <Table.Row>
              <th scope="row" class="py-3 text-left align-top font-normal">
                <div class="flex min-w-0 flex-col gap-1">
                  <span class="font-medium wrap-anywhere">{knowledgeName(source)}</span>
                  {#if source.website_url && source.website_url !== source.name}
                    <span class="text-secondary text-xs wrap-anywhere">{source.website_url}</span>
                  {/if}
                  {#if source.requires_login || source.auto_disabled}
                    <div class="flex flex-wrap gap-1.5">
                      {#if source.requires_login}
                        <Badge variant="outline">{m.admin_spaces_requires_login()}</Badge>
                      {/if}
                      {#if source.auto_disabled}
                        <Badge variant="outline" class="h-auto whitespace-normal">
                          {m.admin_spaces_auto_disabled()}
                        </Badge>
                      {/if}
                    </div>
                  {/if}
                  <!-- What the hidden columns hold, while they are hidden. -->
                  <div class="text-secondary flex flex-col gap-0.5 text-xs @5xl:hidden">
                    <span class="@3xl:hidden">
                      {knowledgeKindLabel(source)} ·
                      {#if source.updated_at}
                        {m.admin_spaces_meta_updated()}
                        {@render updated(source)}
                      {:else}
                        {m.admin_spaces_meta_never_updated()}
                      {/if}
                    </span>
                    <span class="wrap-anywhere">
                      {m.admin_spaces_meta_used_by({ names: usedBy(source) })}
                    </span>
                  </div>
                </div>
              </th>
              <Table.Cell class="hidden @3xl:table-cell">{knowledgeKindLabel(source)}</Table.Cell>
              <Table.Cell class="tabular-nums">{extent(source)}</Table.Cell>
              <Table.Cell class="hidden @3xl:table-cell">{@render updated(source)}</Table.Cell>
              <Table.Cell class="hidden wrap-anywhere @5xl:table-cell">{usedBy(source)}</Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {:else}
    <p class="text-secondary text-sm">{m.admin_spaces_no_knowledge()}</p>
  {/if}

  {#if inheritedCount > 0}
    <p class="text-secondary text-sm">
      {inheritedCount === 1
        ? m.admin_spaces_inherited_one()
        : m.admin_spaces_inherited({ count: number.format(inheritedCount) })}
    </p>
  {/if}
</section>
