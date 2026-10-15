<script lang="ts">
  import { untrack } from "svelte";
  import type { Eneo, Flow } from "@eneo/eneo-js";
  import { initEneo } from "$lib/core/Eneo";
  import { initFlowEditor, type FlowEditor } from "$lib/features/flows/FlowEditor";
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import FlowStepEditPanel from "../FlowStepEditPanel.svelte";

  let { flow, eneo, onEditor }: { flow: Flow; eneo: Eneo; onEditor: (editor: FlowEditor) => void } =
    $props();

  // The flow page's contexts, set up once as the page sets them.
  const editor = untrack(() => {
    initEneo({ eneo });
    initFlowUserMode();
    const created = initFlowEditor({ flow, eneo });
    onEditor(created);
    return created;
  });
  const { update, activeStepId } = editor.state;
</script>

<div data-testid="editor" class="h-[600px] overflow-y-auto">
  <FlowStepEditPanel
    steps={$update.steps ?? []}
    activeStepId={$activeStepId}
    isPublished={false}
    onStepChanged={({ index, step }) => editor.replaceStepAtIndex(index, step)}
  />
</div>
