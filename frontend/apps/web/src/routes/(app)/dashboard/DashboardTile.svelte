<script lang="ts">
  import type { AssistantSparse } from "@intric/intric-js";
  import { dynamicColour } from "$lib/core/colours";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { m } from "$lib/paraglide/messages";
  export let assistant: AssistantSparse;

  // Use localized name for default assistant, otherwise use the assistant's name
  $: displayName = assistant.type === "default-assistant" ? m.personal_assistant() : assistant.name;
</script>

<a
  aria-label={displayName}
  href={localizeHref(`/dashboard/${assistant.id}?tab=chat`)}
  {...dynamicColour({ basedOn: assistant.id })}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {displayName}
  </h2>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
    >{[...displayName][0].toUpperCase()}</span
  >

  <div class="flex-grow"></div>
</a>
