<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { referenceAuditRows } from "@eneo/skill-instructions/audit";
  import { referenceUri } from "@eneo/skill-instructions";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  let {
    evidence,
    toolCalls
  }: {
    evidence: components["schemas"]["SkillActivationEvidenceV3"];
    toolCalls: components["schemas"]["ToolCallInfo"][];
  } = $props();
  let visible = $state(50);
  const rows = $derived(referenceAuditRows(evidence, toolCalls));
  const labels = $derived({
    loaded: m.skills_reference_audit_loaded(),
    called: m.skills_reference_audit_called(),
    available: m.skills_reference_audit_available(),
    unavailable: m.skills_reference_audit_unavailable(),
    not_checked: m.skills_reference_audit_not_checked()
  });
</script>

{#if rows.length}
  <details class="border-border rounded-lg border p-3">
    <summary class="cursor-pointer text-sm font-semibold"
      >{m.skills_reference_audit_title()} ({rows.length})</summary
    >
    <p class="text-muted-foreground my-3 text-xs leading-5">{m.skills_reference_audit_hint()}</p>
    <ol class="flex flex-col gap-3">
      {#each rows.slice(0, visible) as row (row.id)}<li class="flex min-w-0 flex-col gap-1 text-sm">
          <p class="break-words"><strong>{row.source}</strong> → {row.label}</p>
          <p class="text-muted-foreground text-xs">
            {labels[row.state]}{#if row.callOrders.length}
              · {m.skills_reference_audit_calls({ calls: row.callOrders.join(", ") })}{/if}
          </p>
          <details class="text-muted-foreground text-xs">
            <summary class="cursor-pointer">{m.skills_reference_details()}</summary><code
              class="break-all">{referenceUri(row.target)}</code
            >
          </details>
        </li>{/each}
    </ol>
    {#if visible < rows.length}<Button
        type="button"
        variant="ghost"
        onclick={() => {
          visible += 50;
        }}>{m.load_more()}</Button
      >{/if}
  </details>
{/if}
