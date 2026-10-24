<script lang="ts">
  import type { ConversationMessage } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import ConsultationStep from "./ConsultationStep.svelte";

  let {
    consultations,
    streaming
  }: {
    consultations: NonNullable<ConversationMessage["consultations"]>;
    streaming: boolean;
  } = $props();
  const assistantCount = $derived(new Set(consultations.map((item) => item.assistant_id)).size);
  const active = $derived(
    consultations.find((item) => item.status === "running" || item.status === "awaiting_approval")
  );
</script>

<details class="border-dimmer bg-secondary/40 mt-4 rounded-xl border px-3 py-2">
  <summary class="text-muted cursor-pointer py-1 text-sm focus-visible:ring-2">
    {m.consultations_summary({ count: consultations.length, assistants: assistantCount })}
    <span class="ml-2" role="status">
      {#if streaming && active}
        {active.assistant_name} · {active.status === "awaiting_approval"
          ? m.consultation_approval()
          : m.chat_reasoning_working()}
      {/if}
    </span>
  </summary>
  <div class="flex flex-col gap-2 pt-2">
    {#each consultations as consultation (consultation.id)}
      <ConsultationStep {consultation} {streaming} />
    {/each}
  </div>
</details>
