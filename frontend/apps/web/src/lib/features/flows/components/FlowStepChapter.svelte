<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import ChevronDown from "lucide-svelte/icons/chevron-down";
  import { cn } from "$lib/utils.js";

  let {
    title,
    status,
    initialOpen = false,
    resetKey,
    requestOpen,
    class: className,
    children
  }: {
    title: string;
    status?: string;
    initialOpen?: boolean;
    resetKey?: string | number;
    requestOpen?: number;
    class?: string;
    children?: Snippet;
  } = $props();

  let open = $state(untrack(() => initialOpen));
  const openByResetKey = new SvelteMap<string | number | undefined, boolean>();
  let lastResetKey = $state(untrack(() => resetKey));
  $effect(() => {
    if (resetKey !== lastResetKey) {
      openByResetKey.set(lastResetKey, open);
      lastResetKey = resetKey;
      open = untrack(() => openByResetKey.get(resetKey) ?? initialOpen);
    }
  });
  $effect(() => {
    openByResetKey.set(resetKey, open);
  });
  let lastRequestOpen = $state(untrack(() => requestOpen));
  $effect(() => {
    if (requestOpen !== lastRequestOpen) {
      lastRequestOpen = requestOpen;
      open = true;
    }
  });
</script>

<Collapsible.Root bind:open class={cn("border-default border-b", className)}>
  <Collapsible.Trigger
    class="group hover:bg-hover-dimmer/20 focus-visible:ring-accent-default/40 flex min-h-[52px] w-full items-center gap-3 rounded-lg px-2 py-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
  >
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-2">
        <span class="text-primary text-[0.9375rem] font-semibold tracking-[-0.005em]">{title}</span>
      </span>
      {#if status && !open}
        <span class="text-secondary mt-0.5 block truncate text-xs font-normal">{status}</span>
      {/if}
    </span>
    <ChevronDown
      class="text-secondary size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180 motion-reduce:transition-none"
    />
  </Collapsible.Trigger>
  <Collapsible.Content class="collapsible-animate px-2 pt-1 pb-5">
    {@render children?.()}
  </Collapsible.Content>
</Collapsible.Root>
