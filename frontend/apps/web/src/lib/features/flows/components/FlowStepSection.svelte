<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import ChevronDown from "lucide-svelte/icons/chevron-down";
  import { cn } from "$lib/utils.js";

  let {
    title,
    description,
    collapsible = false,
    status,
    initialOpen = false,
    resetKey,
    class: className,
    children
  }: {
    title?: string;
    description?: string;
    collapsible?: boolean;
    status?: string;
    initialOpen?: boolean;
    resetKey?: string | number;
    class?: string;
    children?: Snippet;
  } = $props();

  let open = $state(untrack(() => initialOpen));
  // Re-collapse when the edited step changes (resetKey = step_order), so each
  // step lands on its own default instead of inheriting the previous step's.
  let lastResetKey = $state(untrack(() => resetKey));
  $effect(() => {
    if (resetKey !== lastResetKey) {
      lastResetKey = resetKey;
      open = untrack(() => initialOpen);
    }
  });
</script>

{#if collapsible && title}
  <Collapsible.Root bind:open class={cn("flex flex-col", className)}>
    <Collapsible.Trigger
      class="group hover:bg-hover-dimmer/20 focus-visible:ring-accent-default/40 border-default flex w-full items-center gap-3 border-b px-1.5 pt-1 pb-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <span class="min-w-0 flex-1">
        <h2 class="text-primary text-sm font-semibold tracking-[-0.005em]">
          {title}
        </h2>
        {#if status && !open}
          <span class="text-muted mt-0.5 block truncate text-xs font-normal">{status}</span>
        {/if}
      </span>
      <ChevronDown
        class="text-secondary size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180 motion-reduce:transition-none"
      />
    </Collapsible.Trigger>
    <Collapsible.Content class="collapsible-animate flex flex-col gap-6 px-1.5 pt-5 pb-6">
      {@render children?.()}
    </Collapsible.Content>
  </Collapsible.Root>
{:else}
  <section class={cn("flex flex-col", className)}>
    {#if title}
      <div class="border-default border-b px-1.5 pb-2.5">
        <h2 class="text-primary text-sm font-semibold tracking-[-0.005em]">
          {title}
        </h2>
        {#if description}
          <p class="text-muted mt-1 text-xs leading-relaxed">{description}</p>
        {/if}
      </div>
    {/if}
    <div class="flex flex-col gap-6 px-1.5 pb-6 {title ? 'pt-5' : 'pt-1'}">
      {@render children?.()}
    </div>
  </section>
{/if}
