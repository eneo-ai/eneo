<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import IconArrowLeft from "@lucide/svelte/icons/arrow-left";
  import IconSparkles from "@lucide/svelte/icons/sparkles";
  import {
    FLOW_API_ERROR_CODE,
    getFlowRuntimeErrorMessageByCode
  } from "$lib/features/flows/flowRuntimeErrorMapping";
  import type { FlowRunFailureRepairTarget } from "$lib/features/flows/flowRunFailureRepair";
  import type { AIBuilderFailureRepairState, AIBuilderReviewReference } from "./protocol";
  import { repairFailureCopy } from "./flowFailureRepair";

  interface Props {
    repair: AIBuilderFailureRepairState;
    disabled?: boolean;
    onprepare: (detail: { message: string; reviewContext: AIBuilderReviewReference }) => void;
    onclose: () => void;
    onretry: (target: FlowRunFailureRepairTarget) => void;
  }

  let { repair, disabled = false, onprepare, onclose, onretry }: Props = $props();

  const launch = $derived(repair.status === "ready" ? repair.launch : null);
  const stepName = $derived(launch?.step_name?.trim() || m.flow_step_unnamed());
  const errorLabel = $derived(
    launch ? (getFlowRuntimeErrorMessageByCode(launch.error_code) ?? launch.error_code) : ""
  );
  // What the Builder reads depends on what the run kept: a rejected answer is
  // read as text; a truncated answer was never kept, so the recorded finish
  // reason and token counts are read instead.
  const hint = $derived(
    launch?.error_code === FLOW_API_ERROR_CODE.LLM_OUTPUT_TRUNCATED
      ? m.ai_builder_repair_hint_truncated()
      : m.ai_builder_repair_hint()
  );

  // The server writes the retained sentence from the reference (the step's
  // number); the screen sends the same sentence so what the user saw sent is
  // what the conversation keeps. The step's name stays on this screen.
  function prepare() {
    if (!launch) return;
    onprepare({
      message: m.ai_builder_repair_message({ step: String(launch.step_number) }),
      reviewContext: launch.reference
    });
  }
</script>

<div class="flex flex-1 justify-center px-7 pt-7 pb-8 max-sm:px-3 max-sm:pt-4 max-sm:pb-5">
  <div class="repair-screen w-full max-w-[43.75rem] 2xl:max-w-[48.125rem]">
    <section
      class="border-stronger bg-primary overflow-hidden rounded-xl border shadow-xs"
      aria-label={m.ai_builder_repair_title()}
      data-testid="builder-repair"
    >
      <header
        class="bg-accent-dimmer border-accent-default/25 flex items-start justify-between gap-3 border-b px-5 py-3.5"
      >
        <div class="min-w-0">
          <h2
            class="text-primary text-[1.0625rem] font-bold tracking-[-0.015em]"
            tabindex="-1"
            data-builder-screen-heading
          >
            {m.ai_builder_repair_title()}
          </h2>
          <p class="text-accent-stronger mt-1 text-[0.8125rem] text-pretty">
            {#if launch}
              {m.ai_builder_repair_lead({
                step: String(launch.step_number),
                name: stepName,
                version: String(launch.reference.flow_version)
              })}
            {:else if repair.status === "loading"}
              {m.ai_builder_repair_lead_loading()}
            {/if}
          </p>
        </div>
        <Button variant="outline" size="sm" class="ml-auto shrink-0 gap-1.5" onclick={onclose}>
          <IconArrowLeft class="size-3.5" aria-hidden="true" />
          {m.ai_builder_review_back()}
        </Button>
      </header>

      <div class="px-5 pt-[1.125rem] pb-5">
        {#if repair.status === "loading"}
          <div class="flex flex-col gap-3" aria-busy="true">
            <Skeleton class="h-[4.5rem] w-full rounded-lg" />
          </div>
        {:else if repair.status === "failed"}
          {@const failure = repairFailureCopy(repair.error)}
          <div
            class="bg-warning-dimmer border-warning-default/45 text-warning-stronger rounded-[9px] border px-3 py-2.5 text-[0.8125rem]"
            role="status"
            data-testid="repair-unavailable"
          >
            <p class="font-semibold">{failure.title}</p>
            <p class="mt-0.5">{failure.body}</p>
            {#if failure.retry}
              <Button
                variant="outline"
                size="sm"
                class="mt-2.5"
                onclick={() => onretry(repair.target)}
              >
                {m.ai_builder_review_retry()}
              </Button>
            {/if}
          </div>
        {:else if launch}
          <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[0.875rem]">
            <dt class="text-secondary">{m.ai_builder_repair_error_label()}</dt>
            <dd class="text-primary" data-testid="repair-error">{errorLabel}</dd>
            <dt class="text-secondary">{m.ai_builder_repair_attempt_label()}</dt>
            <dd class="text-primary tabular-nums">{launch.attempt_no}</dd>
          </dl>
          <p class="text-secondary mt-4 text-[0.875rem] text-pretty">
            {hint}
          </p>
          <div class="mt-4">
            <Button class="h-9 gap-1.5" {disabled} onclick={prepare} data-testid="repair-prepare">
              <IconSparkles class="size-4" aria-hidden="true" />
              {m.ai_builder_repair_prepare()}
            </Button>
          </div>
        {/if}
      </div>
    </section>
  </div>
</div>

<style>
  .repair-screen {
    animation: builder-screen-in var(--duration-fast) var(--ease-smooth-out);
  }
  @keyframes builder-screen-in {
    from {
      opacity: 0.4;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .repair-screen {
      animation: none;
    }
  }
</style>
