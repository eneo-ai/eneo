<script lang="ts">
  import AssistantActions from "./AssistantActions.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { dynamicColour } from "$lib/core/colours";
  import GroupChatActions from "./GroupChatActions.svelte";
  import type { AssistantSparse, GroupChatSparse } from "@intric/intric-js";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams";
  import { getAppContext } from "$lib/core/AppContext";

  export let item: AssistantSparse | GroupChatSparse;

  const { environment } = getAppContext();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Generate icon URL from icon_id
  $: iconUrl = item.type === "assistant" && item.icon_id
    ? `${environment.baseUrl}/api/v1/icons/${item.icon_id}/`
    : null;
</script>

<a
  aria-label={item.name}
  {...dynamicColour({ basedOn: item.id })}
  href="/spaces/{$currentSpace.routeId}/chat/?{getChatQueryParams({
    chatPartner: item,
    tab: 'chat'
  })}"
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {item.name}
  </h2>

  <div class="hover:text-primary absolute right-2 bottom-2">
    {#if item.type === "assistant"}
      <AssistantActions assistant={item}></AssistantActions>
    {:else if item.type === "group-chat"}
      <GroupChatActions groupChat={item}></GroupChatActions>
    {/if}
  </div>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
  >
    {#if item.type === "assistant"}
      {#if iconUrl}
        <div class="flex h-32 w-32 items-center justify-center overflow-hidden rounded-xl">
          <img src={iconUrl} alt={item.name} class="h-full w-full object-cover" />
        </div>
      {:else}
        {([...item.name][0] ?? "").toUpperCase()}
      {/if}
    {:else}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="1.5"
        stroke="currentColor"
        class="size-20"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z"
        />
      </svg>
    {/if}</span
  >

  <div class="flex-grow"></div>
</a>
