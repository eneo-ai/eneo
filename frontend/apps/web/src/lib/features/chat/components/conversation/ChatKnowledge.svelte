<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    Read-only knowledge indicator for the chat input toolbar: shows which
    knowledge sources (collections, websites, integrations) are attached to
    the current partner, mirroring how MCP servers are surfaced. Unlike MCP
    servers, knowledge cannot be toggled per conversation, so this only
    informs.
-->
<script lang="ts">
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import { BookOpen } from "lucide-svelte";

  type KnowledgeSource = {
    id: string;
    name: string;
  };

  type Props = {
    collections: KnowledgeSource[];
    websites: KnowledgeSource[];
    integrations: KnowledgeSource[];
    /** The assistant's knowledge_mode ("tool" | "inject"). */
    knowledgeMode?: string;
  };

  let { collections, websites, integrations, knowledgeMode }: Props = $props();

  const total = $derived(collections.length + websites.length + integrations.length);
  const groups = $derived(
    [
      { label: m.collections(), sources: collections },
      { label: m.websites(), sources: websites },
      { label: m.integrations(), sources: integrations }
    ].filter((group) => group.sources.length > 0)
  );
</script>

<Popover.Root>
  <Popover.Trigger
    class={buttonVariants({ variant: "secondary", size: "sm" }) + " h-9 gap-1.5 rounded-lg"}
    title={m.knowledge()}
    aria-label={m.knowledge_attached_aria({ count: total })}
  >
    <BookOpen class="size-4" aria-hidden="true" />
    <span class="hidden sm:inline">{m.knowledge()}</span>
    <Badge variant="default" class="ml-0.5 px-1.5 tabular-nums" aria-hidden="true">{total}</Badge>
  </Popover.Trigger>

  <Popover.Content side="top" align="start" class="w-80 gap-0 p-0">
    <div class="border-b px-3 py-2.5">
      <Popover.Title class="text-sm">{m.knowledge()}</Popover.Title>
      <p class="text-muted-foreground mt-0.5 text-xs">
        {knowledgeMode === "inject" ? m.knowledge_mode_inject_hint() : m.knowledge_mode_tool_hint()}
      </p>
    </div>

    <div class="flex max-h-64 flex-col overflow-y-auto p-1" role="list" aria-label={m.knowledge()}>
      {#each groups as group (group.label)}
        <p class="text-muted-foreground px-2 pb-0.5 pt-2 text-xs font-medium">{group.label}</p>
        {#each group.sources as source (source.id)}
          <div class="flex items-center gap-2.5 rounded-md px-2 py-1.5" role="listitem">
            <span
              class="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold"
              aria-hidden="true"
            >
              {source.name.charAt(0).toUpperCase()}
            </span>
            <span class="text-foreground min-w-0 flex-1 truncate text-sm">{source.name}</span>
          </div>
        {/each}
      {/each}
    </div>
  </Popover.Content>
</Popover.Root>
