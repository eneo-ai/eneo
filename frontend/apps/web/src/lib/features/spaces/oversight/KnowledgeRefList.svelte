<!--
  The knowledge an assistant uses: names and kinds, never document titles.
  Sources that carry counts (the widget review) also show how many documents
  or pages they hold.
-->
<script lang="ts">
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import {
    knowledgeItemCount,
    knowledgeKindLabel,
    knowledgeName,
    type OversightKnowledge
  } from "./knowledge";

  type Props = {
    items: readonly OversightKnowledge[];
    /** Shown instead of the list when there is no knowledge. */
    emptyText?: string;
  };

  let { items, emptyText }: Props = $props();

  const number = $derived(new Intl.NumberFormat(intlLocale()));

  function details(source: OversightKnowledge): string[] {
    const parts: string[] = [];
    // A nameless source is a OneDrive folder, and its name already says so.
    if (source.name) parts.push(knowledgeKindLabel(source));
    if ("item_count" in source) parts.push(knowledgeItemCount(source, number.format));
    if ("from_organization" in source && source.from_organization) {
      parts.push(m.admin_spaces_from_org());
    }
    return parts;
  }
</script>

{#if items.length === 0}
  <p class="text-secondary text-sm">{emptyText ?? m.admin_spaces_none()}</p>
{:else}
  <ul class="flex flex-col gap-1.5 text-sm">
    {#each items as source (`${source.kind}-${source.id}`)}
      {@const meta = details(source)}
      <li class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span class="min-w-0 break-words">{knowledgeName(source)}</span>
        {#if meta.length > 0}
          <span class="text-secondary text-xs">{meta.join(" · ")}</span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}
