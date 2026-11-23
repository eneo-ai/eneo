<script lang="ts">
  import { goto } from "$app/navigation";
  import ResourceSwitcher from "$lib/components/ResourceSwitcher.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "../../ChatService.svelte";
  import { getChatQueryParams } from "../../getChatQueryParams";

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const chat = getChatService();
</script>

<ResourceSwitcher
  items={$currentSpace.applications.chat}
  current={chat.partner}
  heading={m.select_an_assistant()}
  onSelect={(partner) => {
    const url = `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: partner })}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space id and chat query params
    goto(url);
  }}
>
  {#snippet itemIcon(partner)}
    <div class="relative flex-shrink-0">
      {#if partner.icon_id}
        <div class="h-10 w-10 overflow-hidden rounded-lg">
          <img
            src={eneo.icons.url({ id: partner.icon_id })}
            alt=""
            class="h-full w-full object-cover"
          />
        </div>
      {:else}
        <SpaceChip space={{ ...partner, personal: false }} />
      {/if}
    </div>
  {/snippet}
</ResourceSwitcher>
