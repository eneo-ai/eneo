<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import ChevronDown from "lucide-svelte/icons/chevron-down";
  import { cn } from "$lib/utils.js";

  // A collapsible chapter that groups related step sections. Renders as a flat
  // disclosure row separated by a divider (not a card) so the editor reads as one
  // calm settings surface rather than a stack of bordered cards. Multiple
  // chapters can be open at once (each owns its state); the collapsed header
  // keeps a one-line status so nothing feels hidden. Built on shadcn Collapsible
  // for the button semantics + aria-expanded.
  let {
    title,
    status,
    badge,
    initialOpen = false,
    resetKey,
    requestOpen,
    class: className,
    children
  }: {
    title: string;
    status?: string;
    badge?: string;
    initialOpen?: boolean;
    resetKey?: string | number;
    requestOpen?: number;
    class?: string;
    children?: Snippet;
  } = $props();

  let open = $state(untrack(() => initialOpen));
  // Re-apply the default open state when the edited step changes (resetKey =
  // step_order), so each step lands on its own default instead of inheriting the
  // previous step's open sections. Within a step, the user's toggles persist.
  let lastResetKey = $state(untrack(() => resetKey));
  $effect(() => {
    if (resetKey !== lastResetKey) {
      lastResetKey = resetKey;
      open = untrack(() => initialOpen);
    }
  });
  // An external request (e.g. clicking the capsule warning) forces the chapter
  // open; bumping `requestOpen` is the signal.
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
        <span class="text-primary text-sm font-semibold tracking-[-0.005em]">{title}</span>
        {#if badge}
          <span
            class="border-default text-secondary shrink-0 rounded-full border px-1.5 py-0.5 text-xs font-medium"
          >
            {badge}
          </span>
        {/if}
      </span>
      {#if status && !open}
        <span class="text-secondary mt-0.5 block truncate text-xs font-normal">{status}</span>
      {/if}
    </span>
    <ChevronDown
      class="text-secondary size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180"
    />
  </Collapsible.Trigger>
  <Collapsible.Content class="px-2 pt-1 pb-5">
    {@render children?.()}
  </Collapsible.Content>
</Collapsible.Root>
