<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";

  let { step }: { step: FlowStep } = $props();
</script>

{#if step.output_type === "json" && step.output_contract}
  <div
    class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
  >
    {m.flow_typed_io_json_contract_info()}
  </div>
{/if}

{#if (step.output_type === "pdf" || step.output_type === "docx") && step.output_contract}
  <div
    class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
  >
    {m.flow_typed_io_doc_contract_info()}
  </div>
{/if}

{#if step.input_type === "document" && step.step_order === 1}
  <div
    class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
  >
    {m.flow_typed_io_document_input_info()}
  </div>
{/if}

{#if step.input_type === "image"}
  <div
    class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
  >
    {m.flow_typed_io_image_not_supported()}
  </div>
{/if}
