<script lang="ts">
  import type { SkillBindingSummary } from "@eneo/eneo-js";
  import { ArrowRight, Layers3 } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    bindings: SkillBindingSummary[];
    manageHref?: string;
  };

  let { bindings, manageHref }: Props = $props();

  const orderedBindings = $derived([...bindings].sort((a, b) => a.position - b.position));
</script>

{#if orderedBindings.length > 0}
  <Popover.Root>
    <Popover.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="ghost"
          size="sm"
          class="text-muted-foreground hover:text-foreground shrink-0 gap-1.5"
          aria-label={m.skills_chat_summary_count({ count: String(orderedBindings.length) })}
        >
          <Layers3 aria-hidden="true" />
          <span class="hidden xl:inline">{m.skills()}</span>
          <Badge variant="secondary" class="h-5 min-w-5 justify-center px-1.5 tabular-nums">
            {orderedBindings.length}
          </Badge>
        </Button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content align="end" class="w-96 max-w-[calc(100vw-2rem)] gap-0 p-0">
      <div class="border-b px-4 py-3">
        <Popover.Title class="text-sm">{m.skills_chat_summary_title()}</Popover.Title>
        <p class="text-muted-foreground mt-1 text-xs leading-5">
          {m.skills_chat_summary_description()}
        </p>
      </div>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
      <div
        class="flex max-h-[min(32rem,calc(100dvh-8rem))] flex-col overflow-y-auto overscroll-contain p-1 [scrollbar-gutter:stable]"
        role="region"
        aria-label={m.skills_binding_scroll_region_label({
          count: String(orderedBindings.length)
        })}
        tabindex="0"
      >
        <ol class="flex flex-col" aria-label={m.skills_binding_order_label()}>
          {#each orderedBindings as binding, index (binding.skill_revision_id)}
            <li class="flex items-start gap-3 rounded-md px-3 py-2.5">
              <Badge variant="outline" class="mt-0.5 min-w-6 justify-center px-1.5 tabular-nums">
                {index + 1}
              </Badge>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <p class="text-sm font-medium">{binding.display_name}</p>
                  <span class="text-muted-foreground text-xs">
                    {m.skills_revision_label({ revision: String(binding.revision_number) })}
                  </span>
                </div>
                <p class="text-muted-foreground mt-0.5 text-xs leading-5">
                  {binding.description}
                </p>
              </div>
            </li>
          {/each}
        </ol>
      </div>
      {#if manageHref}
        <div class="border-t p-1">
          <Button href={manageHref} variant="ghost" size="sm" class="w-full justify-between">
            {m.skills_manage_bindings_action()}
            <ArrowRight data-icon="inline-end" aria-hidden="true" />
          </Button>
        </div>
      {/if}
    </Popover.Content>
  </Popover.Root>
{/if}
