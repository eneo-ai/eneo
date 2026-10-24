<script lang="ts">
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { AssistantSparse } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams";
  import ResourceTile from "$lib/features/spaces/components/ResourceTile.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import AssistantActions from "./AssistantActions.svelte";

  let { item }: { item: AssistantSparse } = $props();

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
      </div>
    {:else}
      {([...item.name][0] ?? "").toUpperCase()}
    {/if}
  {/snippet}
  {#snippet actions()}
    <AssistantActions assistant={item} />
  {/snippet}
</ResourceTile>
