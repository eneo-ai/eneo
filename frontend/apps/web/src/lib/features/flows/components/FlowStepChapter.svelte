<script lang="ts">
  import { tick, untrack, type Snippet } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { cn } from "$lib/utils.js";
  import { focusStepTarget, type StepFocusTarget } from "$lib/features/flows/flowStepFocus";

  let {
    title,
    status,
    statusTone = "default",
    initialOpen = false,
    resetKey,
    requestOpen,
    focusTarget = null,
    onFocusTaken,
    class: className,
    children
  }: {
    title: string;
    status?: string;
    /** "warning" when the summary reports something the step still needs. */
    statusTone?: "default" | "warning";
    initialOpen?: boolean;
    resetKey?: string | number;
    requestOpen?: number;
    /** A place inside the chapter to land on: the chapter opens and the place takes the focus. */
    focusTarget?: StepFocusTarget | null;
    /** Called once the chapter has taken `focusTarget`, so the owner drops it. */
    onFocusTaken?: () => void;
    class?: string;
    children?: Snippet;
  } = $props();

  let open = $state(untrack(() => initialOpen));
  const openByResetKey = new SvelteMap<string | number | undefined, boolean>();
  let lastResetKey = $state(untrack(() => resetKey));
  // Counts landings; another step shown (a new reset key) cancels the one
  // still waiting for the chapter to open, which would land in that step.
  let landing = 0;
  $effect(() => {
    if (resetKey !== lastResetKey) {
      landing += 1;
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
  // The content is inert while closed and clips its rows while it opens, so
  // the place is scrolled to and focused once the opened chapter has rendered
  // and its opening animation has ended.
  let contentEl = $state<HTMLElement | null>(null);
  async function landWhenOpen(root: HTMLElement, target: StepFocusTarget) {
    const mine = ++landing;
    await tick();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await Promise.allSettled(root.getAnimations().map((animation) => animation.finished));
    if (mine === landing) focusStepTarget(root, target);
  }
  $effect(() => {
    const target = focusTarget;
    const root = contentEl;
    if (!target || !root) return;
    untrack(() => onFocusTaken?.());
    open = true;
    void landWhenOpen(root, target);
  });
</script>

<Collapsible.Root bind:open class={cn("border-default border-b", className)}>
  <Collapsible.Trigger
    class="group hover:bg-hover-dimmer/20 focus-visible:ring-ring flex min-h-[52px] w-full items-center gap-3 rounded-lg px-2 py-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
  >
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-2">
        <span class="text-primary text-[0.9375rem] font-semibold tracking-[-0.005em]">{title}</span>
      </span>
      {#if status && !open}
        <span
          class={cn(
            "mt-0.5 block truncate text-xs font-normal",
            statusTone === "warning" ? "text-warning-stronger font-medium" : "text-secondary"
          )}>{status}</span
        >
      {/if}
    </span>
    <ChevronDown
      class="text-secondary size-4 shrink-0 group-data-[state=open]:rotate-180 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) motion-reduce:transition-none"
    />
  </Collapsible.Trigger>
  <Collapsible.Content
    bind:ref={contentEl}
    class="collapsible-animate px-2 pt-1 pb-5"
    inert={!open}
    aria-hidden={!open}
  >
    {@render children?.()}
  </Collapsible.Content>
</Collapsible.Root>
