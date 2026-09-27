<script lang="ts">
  import { goto } from "$app/navigation";
  import { IconPeople } from "@eneo/icons/people";
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
        {#if partner.type === "group-chat"}
          <div
            class="bg-primary border-default text-secondary absolute -right-1.5 -bottom-1.5 flex h-5 w-5 items-center justify-center rounded-full border shadow-sm"
          >
            <IconPeople class="!h-3 !w-3" />
          </div>
        {/if}
      {:else if partner.type === "group-chat"}
        <div
          class="bg-hover-default text-secondary flex h-10 w-10 items-center justify-center rounded-lg"
        >
          <IconPeople class="!h-5 !w-5" />
        </div>
      {:else}
        <SpaceChip space={{ ...partner, personal: false }} />
      {/if}
    </div>
  {/snippet}
</ResourceSwitcher>
