<script lang="ts">
  import type { ComponentProps } from "svelte";
  import FlowStepChapter from "../FlowStepChapter.svelte";
  import ToolConfigPanel from "../tool/ToolConfigPanel.svelte";
  import type { StepFocusTarget } from "$lib/features/flows/flowStepFocus";
  import { m } from "$lib/paraglide/messages";

  let {
    stepKey,
    focusTarget,
    onFocusTaken,
    panel
  }: {
    stepKey: string;
    focusTarget: StepFocusTarget | null;
    onFocusTaken: () => void;
    panel: ComponentProps<typeof ToolConfigPanel>;
  } = $props();
</script>

<!-- A step editor's scroll box, with the chapters above Underlag taking more than its height. -->
<div data-testid="editor" class="h-[400px] overflow-y-auto">
  <div class="h-[1600px]"></div>
  <FlowStepChapter title={m.flow_chapter_input()} resetKey={stepKey} {focusTarget} {onFocusTaken}>
    <ToolConfigPanel {...panel} />
  </FlowStepChapter>
</div>
