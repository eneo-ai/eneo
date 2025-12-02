<script lang="ts">
  import type { AssistantSparse } from "@intric/intric-js";
  import { dynamicColour } from "$lib/core/colours";
  export let assistant: AssistantSparse;
</script>

<a
  aria-label={assistant.name}
  href="/dashboard/{assistant.id}?tab=chat"
  {...dynamicColour({ basedOn: assistant.id })}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    Assistant: {assistant.name}
  </h2>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
    >{[...assistant.name][0].toUpperCase()}</span
  >

  <div class="flex-grow"></div>
</a>
