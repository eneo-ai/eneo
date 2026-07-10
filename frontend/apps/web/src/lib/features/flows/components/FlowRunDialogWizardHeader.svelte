<script lang="ts">
  import type { FlowRunWizardPage } from "$lib/features/flows/flowRunWizard";
  import { m } from "$lib/paraglide/messages";

  let {
    wizardPages,
    currentPage,
    currentPageIndex,
    progressLabel,
    currentInputPosition,
    runtimeInputTotal,
    onGoToPage
  }: {
    wizardPages: FlowRunWizardPage[];
    currentPage: FlowRunWizardPage;
    currentPageIndex: number;
    progressLabel: string;
    currentInputPosition: number;
    runtimeInputTotal: number;
    onGoToPage: (pageId: FlowRunWizardPage["id"]) => void;
  } = $props();
</script>

<div class="border-default/60 shrink-0 border-b px-4 py-4 sm:px-6 lg:px-8">
  <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_17rem] md:items-center">
    <div class="min-w-0">
      <p class="text-muted mb-1 text-xs font-medium tracking-[0.08em] uppercase">
        {#if currentPage.kind === "runtime-step"}
          {m.flow_run_input_progress({
            n: String(currentInputPosition),
            total: String(runtimeInputTotal)
          })}
        {:else}
          {progressLabel}
        {/if}
      </p>
      <h3
        class="text-primary text-base font-semibold tracking-tight sm:text-lg"
        data-wizard-heading
        tabindex="-1"
      >
        {#if currentPage.kind === "runtime-step"}
          {m.flow_run_input_for_step({
            order: String(currentPage.stepOrder),
            name: currentPage.stepLabel
          })}
        {:else}
          {currentPage.title}
        {/if}
      </h3>
      <p class="text-secondary mt-1 text-sm leading-relaxed">
        {currentPage.description}
      </p>
    </div>
    <nav class="flex items-center gap-1.5" aria-label={progressLabel}>
      {#each wizardPages as page, pageIndex (page.id)}
        {@const isCompleted = pageIndex < currentPageIndex}
        {@const isCurrent = pageIndex === currentPageIndex}
        {@const isClickable = isCompleted}
        <button
          type="button"
          title={page.title}
          class="focus-visible:ring-ring/50 relative h-1.5 flex-1 rounded-full transition-colors duration-200 before:absolute before:-inset-x-0 before:-inset-y-5 before:content-[''] focus-visible:ring-2 focus-visible:ring-offset-2 {isCompleted
            ? 'bg-accent-default'
            : isCurrent
              ? 'bg-accent-default/55'
              : 'bg-hover-dimmer'}"
          aria-label={page.title}
          aria-current={isCurrent ? "step" : undefined}
          disabled={!isClickable}
          class:cursor-pointer={isClickable}
          class:cursor-default={!isClickable}
          onclick={() => {
            if (isClickable) onGoToPage(page.id);
          }}
        ></button>
      {/each}
    </nav>
  </div>
</div>
