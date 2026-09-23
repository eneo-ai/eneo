<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  interface Props {
    stepNumber: number;
    name: string;
    /** "Läser steg 1 och 2 · Svarar med 3 fasta fält": what the step takes and gives. */
    detail: string;
    /** How a step works when it does not ask an AI model, e.g. "Sammanställer text". */
    modeLabel?: string | null;
    /** An unchanged step in a diff: present for context, not for reading. */
    quiet?: boolean;
    /** The run stops here until a person approves. */
    pausesForReview?: boolean;
    /** The step runs once per uploaded file or per item. */
    perFile?: boolean;
    changeBadge?: "new" | "updated" | "changes" | null;
  }

  let {
    stepNumber,
    name,
    detail,
    modeLabel = null,
    quiet = false,
    pausesForReview = false,
    perFile = false,
    changeBadge = null
  }: Props = $props();

  const highlighted = $derived(changeBadge === "new" || changeBadge === "changes");
</script>

<!-- A step the latest revision touched glows once so the eye lands on what
     changed; the badge stays as the durable marker. -->
<div
  class="flex items-start gap-3 rounded-[10px] border px-3.5 py-3 {highlighted
    ? 'border-accent-default/30 bg-accent-dimmer/40'
    : quiet
      ? 'border-dimmer bg-primary'
      : 'border-default bg-primary'} {changeBadge === 'updated' ? 'step-updated' : ''}"
>
  <span
    class="mt-px inline-flex size-[1.625rem] shrink-0 items-center justify-center rounded-md text-xs font-bold tabular-nums
      {pausesForReview
      ? 'bg-warning-dimmer text-warning-stronger'
      : quiet
        ? 'bg-secondary text-secondary'
        : 'bg-accent-dimmer text-accent-stronger'}"
  >
    <span class="sr-only">{m.ai_builder_step_label({ step: stepNumber })}</span>
    <span aria-hidden="true">{stepNumber}</span>
  </span>
  <div class="min-w-0 flex-1">
    <div class="flex flex-wrap items-center gap-1.5">
      <span
        class="min-w-0 flex-1 truncate text-[0.9375rem] tracking-[-0.01em] {quiet
          ? 'text-primary font-medium'
          : 'text-primary font-semibold'}"
        title={name}
      >
        {name}
      </span>
      {#if pausesForReview}
        <span
          class="bg-warning-dimmer text-warning-stronger inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-semibold whitespace-nowrap"
          title={m.ai_builder_node_review_checkpoint_hint()}
        >
          {m.ai_builder_node_review_checkpoint()}
        </span>
      {/if}
      {#if perFile}
        <span
          class="bg-secondary text-secondary inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-medium whitespace-nowrap"
          title={m.ai_builder_node_per_file_hint()}
        >
          {m.ai_builder_node_per_file()}
        </span>
      {/if}
      {#if changeBadge}
        <span
          class="inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-semibold whitespace-nowrap
            {changeBadge === 'new'
            ? 'bg-positive-dimmer text-positive-stronger'
            : 'bg-accent-dimmer text-accent-stronger'}"
        >
          {changeBadge === "new"
            ? m.ai_builder_badge_new()
            : changeBadge === "changes"
              ? m.ai_builder_node_changes()
              : m.ai_builder_node_updated()}
        </span>
      {:else if quiet}
        <span class="sr-only">{m.ai_builder_node_unchanged()}</span>
      {/if}
    </div>
    <p class="text-secondary mt-0.5 text-xs leading-relaxed text-pretty">{detail}</p>
  </div>
  {#if modeLabel}
    <span
      class="text-secondary inline-flex max-w-[12rem] shrink-0 items-center truncate text-xs font-medium max-sm:hidden"
      title={modeLabel}
    >
      {modeLabel}
    </span>
  {/if}
</div>

<style lang="postcss">
  .step-updated {
    animation: step-updated 1.4s ease-out 1;
  }
  @keyframes step-updated {
    from {
      background-color: var(--accent-dimmer);
    }
    to {
      background-color: var(--background-primary);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .step-updated {
      animation: none;
    }
  }
</style>
