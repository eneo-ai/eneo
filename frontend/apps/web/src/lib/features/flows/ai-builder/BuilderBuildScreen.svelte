<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import type { AIBuilderStatus } from "./protocol";

  interface Props {
    status: AIBuilderStatus | null;
    /** Number of skeleton rows: the last known plan length, or a typical five. */
    stepCount?: number;
  }

  let { status, stepCount = 5 }: Props = $props();

  // Only backend-reported phases are narrated; nothing here simulates progress.
  const narration = $derived.by(() => {
    switch (status) {
      case "architecture_committed":
      case "architecture_revised":
        return m.ai_builder_build_narration_steps();
      case "repairing":
        return m.ai_builder_build_narration_checking();
      default:
        return m.ai_builder_build_narration_reading();
    }
  });
</script>

<div class="flex justify-center px-7 pt-6 pb-10 max-sm:px-3 max-sm:pt-4">
  <div class="w-full max-w-[43.75rem]">
    <div class="border-default bg-primary overflow-hidden rounded-xl border">
      <div class="px-5 pt-[1.125rem] pb-4">
        <h2 class="text-primary text-[1.0625rem] font-bold tracking-[-0.015em]">
          {m.ai_builder_build_title()}
        </h2>
        <p class="text-secondary mt-1 text-[0.8125rem] text-pretty">
          {m.ai_builder_build_subtitle()}
        </p>
        <p class="text-secondary mt-2.5 text-[0.8125rem]" role="status" aria-live="polite">
          {narration} …
        </p>
      </div>
      <div class="border-dimmer flex flex-col gap-2 border-t px-5 pt-4 pb-5" aria-hidden="true">
        {#each Array.from({ length: Math.max(1, Math.min(stepCount, 12)) }) as _, i (i)}
          <div
            class="border-dimmer bg-secondary flex min-h-[3.625rem] items-center gap-3 rounded-[10px] border px-3 py-3"
          >
            <span
              class="bg-tertiary text-secondary inline-flex size-6 shrink-0 items-center justify-center rounded-[7px] text-xs font-bold"
            >
              {i + 1}
            </span>
            <div class="flex flex-1 flex-col gap-[0.4375rem]">
              <Skeleton
                class="bg-tertiary h-[0.6875rem] rounded"
                style="width: {[62, 74, 58, 68, 48][i % 5]}%"
              />
              <Skeleton
                class="bg-tertiary h-[0.5625rem] rounded"
                style="width: {[38, 44, 34, 40, 30][i % 5]}%"
              />
            </div>
          </div>
        {/each}
      </div>
      <div class="border-default bg-secondary border-t px-5 py-3">
        <p class="text-secondary text-[0.8125rem]">{m.ai_builder_build_footer()}</p>
      </div>
    </div>
  </div>
</div>
