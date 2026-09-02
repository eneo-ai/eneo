<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  interface Props {
    stepNumber: number;
    name: string;
    /** "Ljud → Text" — what the step takes in and hands on. */
    ioLabel: string;
    modelLabel: string;
    /** An unchanged step in a diff: present for context, not for reading. */
    quiet?: boolean;
    /** "PDF-dokument" when the step writes a file the run keeps. */
    artifactLabel?: string | null;
    /** The run stops here until a person approves. */
    pausesForReview?: boolean;
    /** The step runs once per uploaded file or per item. */
    perFile?: boolean;
    changeBadge?: "new" | "updated" | "unchanged" | null;
  }

  let {
    stepNumber,
    name,
    ioLabel,
    modelLabel,
    quiet = false,
    artifactLabel = null,
    pausesForReview = false,
    perFile = false,
    changeBadge = null
  }: Props = $props();
</script>

<div
  class="flex items-start gap-3 rounded-[10px] border px-3.5 py-3 {quiet
    ? 'border-dimmer bg-secondary'
    : 'border-default bg-primary shadow-sm'}"
>
  <span
    class="mt-px inline-flex size-[1.625rem] shrink-0 items-center justify-center rounded-[7px] text-xs font-bold tabular-nums
      {pausesForReview
      ? 'bg-warning-dimmer text-warning-stronger'
      : 'bg-accent-dimmer text-accent-stronger'}"
    aria-hidden="true"
  >
    {stepNumber}
  </span>
  <div class="min-w-0 flex-1">
    <div class="flex flex-wrap items-center gap-1.5">
      <span
        class="text-primary min-w-0 flex-1 truncate text-[0.875rem] font-semibold tracking-[-0.01em]"
        title={name}
      >
        {name}
      </span>
      {#if pausesForReview}
        <span
          class="bg-warning-dimmer text-warning-stronger inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-semibold whitespace-nowrap"
          title={m.ai_builder_node_review_checkpoint_hint()}
        >
          {m.ai_builder_node_review_checkpoint()}
        </span>
      {/if}
      {#if perFile}
        <span
          class="bg-secondary text-secondary inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-medium whitespace-nowrap"
          title={m.ai_builder_node_per_file_hint()}
        >
          {m.ai_builder_node_per_file()}
        </span>
      {/if}
      {#if changeBadge}
        <span
          class="inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-semibold whitespace-nowrap
            {changeBadge === 'new'
            ? 'bg-positive-dimmer text-positive-stronger'
            : changeBadge === 'updated'
              ? 'bg-accent-dimmer text-accent-stronger'
              : 'text-secondary'}"
        >
          {changeBadge === "new"
            ? m.ai_builder_badge_new()
            : changeBadge === "updated"
              ? m.ai_builder_node_updated()
              : m.ai_builder_node_unchanged()}
        </span>
      {/if}
    </div>
    <div class="text-secondary mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
      <span>{ioLabel}</span>
      {#if artifactLabel}
        <span
          class="border-default text-primary inline-flex h-[1.1875rem] items-center rounded-[5px] border px-1.5 text-[0.65625rem] font-semibold"
        >
          {artifactLabel}
        </span>
      {/if}
    </div>
  </div>
  <span
    class="text-secondary inline-flex max-w-[14rem] shrink-0 items-center truncate text-[0.71875rem] font-medium max-lg:max-w-[5.5rem] max-sm:hidden"
    title={modelLabel}
  >
    {modelLabel}
  </span>
</div>
