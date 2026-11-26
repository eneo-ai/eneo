<script lang="ts">
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { AssistantSparse, GroupChatSparse } from "@eneo/eneo-js";
  import { IconPeople } from "@eneo/icons/people";
  import { getEneo } from "$lib/core/Eneo";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams";
  import ResourceTile from "$lib/features/spaces/components/ResourceTile.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import AssistantActions from "./AssistantActions.svelte";
  import GroupChatActions from "./GroupChatActions.svelte";

  let { item }: { item: AssistantSparse | GroupChatSparse } = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<ResourceTile
  href={localizeHref(
    `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: item, tab: "chat" })}`
  )}
  name={item.name}
  id={item.id}
>
  {#snippet icon()}
    {#if item.icon_id}
      <div class="relative flex h-32 w-32 items-center justify-center overflow-hidden rounded-xl">
        <img
          src={eneo.icons.url({ id: item.icon_id })}
          alt={item.name}
          class="h-full w-full object-cover"
        />
        {#if item.type === "group-chat"}
          <div
            class="bg-primary/80 absolute -right-1 -bottom-1 flex h-8 w-8 items-center justify-center rounded-full border border-current text-inherit backdrop-blur-sm"
          >
            <IconPeople class="h-5 w-5" />
          </div>
        {/if}
      </div>
    {:else if item.type === "group-chat"}
      <IconPeople class="size-20" />
    {:else}
      {([...item.name][0] ?? "").toUpperCase()}
    {/if}
  {/snippet}
  {#snippet actions()}
    {#if item.type === "assistant"}
      <AssistantActions assistant={item} />
    {:else if item.type === "group-chat"}
      <GroupChatActions groupChat={item} />
    {/if}
  {/snippet}
</ResourceTile>
