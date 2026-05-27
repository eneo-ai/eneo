<script lang="ts">
  import type { Flow, Intric } from "@intric/intric-js";
  import { onDestroy } from "svelte";

  import { initFlowEditor, type FlowEditor } from "../../FlowEditor";
  import { initFlowUserMode } from "../../FlowUserMode";
  import FlowFormSchemaEditor from "../FlowFormSchemaEditor.svelte";

  export let flow: Flow;
  export let intric: Intric;
  export let isPublished = false;
  export let onEditor: ((editor: FlowEditor) => void) | undefined = undefined;

  initFlowUserMode();
  const editor = initFlowEditor({ flow, intric });
  const {
    state: { update }
  } = editor;

  onEditor?.(editor);

  onDestroy(() => {
    editor.destroy();
  });
</script>

<FlowFormSchemaEditor {isPublished} />
<output data-testid="metadata-json">{JSON.stringify($update.metadata_json)}</output>
