<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Linear stepper used by the AddWizard. Three states per step:
    - active     — currently shown
    - completed  — passed (and clickable to revisit)
    - upcoming   — not yet reached (not clickable)

  Implemented as a labelled <nav> with <button>s so screenreaders can move
  between steps with the standard tab order. We do NOT use Tabs here: tabs
  imply random-access between mutually-exclusive views, while a stepper has
  a directional flow with strict prerequisites.
-->

<script lang="ts">
  import Check from "lucide-svelte/icons/check";

  export interface Step {
    id: string;
    label: string;
    /** Allow the user to jump directly to this step from the indicator. */
    canJumpTo?: boolean;
  }

  let {
    steps,
    currentId,
    onJump,
    "aria-label": ariaLabel
  }: {
    steps: ReadonlyArray<Step>;
    currentId: string;
    onJump: (id: string) => void;
    /** Accessible name for the step list. Should be localised by the caller. */
    "aria-label": string;
  } = $props();

  const currentIndex = $derived(steps.findIndex((s) => s.id === currentId));

  function statusOf(index: number): "active" | "completed" | "upcoming" {
    if (index === currentIndex) return "active";
    if (index < currentIndex) return "completed";
    return "upcoming";
  }
</script>

<nav class="flex items-center" aria-label={ariaLabel}>
  {#each steps as step, i (step.id)}
    {@const status = statusOf(i)}
    {@const clickable = status === "completed" || (status !== "active" && step.canJumpTo)}
    <button
      type="button"
      data-status={status}
      aria-current={status === "active" ? "step" : undefined}
      disabled={!clickable}
      onclick={() => clickable && onJump(step.id)}
      class="
        focus-visible:ring-ring/50 data-[status=active]:text-foreground data-[status=completed]:text-positive-stronger data-[status=completed]:hover:text-positive-default data-[status=upcoming]:text-muted-foreground relative flex items-center gap-2
        rounded-sm px-1 py-2 text-sm
        transition-colors duration-150
        focus-visible:ring-3
        focus-visible:outline-none
        disabled:cursor-default data-[status=active]:font-medium
        data-[status=upcoming]:tracking-wide
      "
    >
      {#if status === "completed"}
        <Check class="text-positive-default h-4 w-4" aria-hidden="true" />
      {/if}
      <span>{step.label}</span>
      {#if status === "active"}
        <span
          aria-hidden="true"
          class="bg-accent-default absolute right-1 bottom-0 left-1 h-0.5 rounded-full"
        ></span>
      {/if}
    </button>
    {#if i < steps.length - 1}
      <div
        aria-hidden="true"
        class="mx-3 h-px w-8 transition-colors duration-150"
        class:bg-positive-default={i < currentIndex}
        class:bg-border={i >= currentIndex}
      ></div>
    {/if}
  {/each}
</nav>
