<script lang="ts">
  import type { SkillBindingSummary } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  let { dependencies }: { dependencies: SkillBindingSummary["dependencies"] } = $props();
</script>

{#if dependencies?.length}
  <details class="text-muted-foreground mt-2 text-xs">
    <summary class="cursor-pointer"
      >{m.skills_reference_dependencies()} ({dependencies.length})</summary
    >
    <ul class="mt-2 flex flex-col gap-1">
      {#each dependencies as item (item.skill_id)}<li class="break-words">
          {item.display_name} · {m.skills_revision_label({
            revision: String(item.revision_number)
          })}
        </li>{/each}
    </ul>
  </details>
{/if}
