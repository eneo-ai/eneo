<script lang="ts">
  import type { Flow, Eneo } from "@eneo/eneo-js";
  import { onDestroy } from "svelte";

  import { initFlowEditor, type FlowEditor } from "../../FlowEditor";
  import { initFlowUserMode } from "../../FlowUserMode";
  import FlowFormSchemaEditor from "../FlowFormSchemaEditor.svelte";

  export let flow: Flow;
  export let eneo: Eneo;
  export let isPublished = false;
  export let onEditor: ((editor: FlowEditor) => void) | undefined = undefined;

  initFlowUserMode();
  const editor = initFlowEditor({ flow, eneo });
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
