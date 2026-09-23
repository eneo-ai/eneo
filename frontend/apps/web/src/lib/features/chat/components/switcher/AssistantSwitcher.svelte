<script lang="ts">
  import { IconChevronUpDown } from "@eneo/icons/chevron-up-down";
  import { IconPeople } from "@eneo/icons/people";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Select as SelectPrimitive } from "bits-ui";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { goto } from "$app/navigation";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import type { AssistantSparse, GroupChatSparse } from "@eneo/eneo-js";
  import { getChatQueryParams } from "../../getChatQueryParams";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  const { environment } = getAppContext();

  // Helper function to get icon URL from icon_id
  function getIconUrl(partner: AssistantSparse | GroupChatSparse): string | null {
    if (partner.icon_id) {
      return `${environment.baseUrl}/api/v1/icons/${partner.icon_id}/`;
    }
    return null;
  }

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const chat = getChatService();

  function openPartner(id: string) {
    const partner = $currentSpace.applications.chat.find((candidate) => candidate.id === id);
    if (!partner) return;
    const url = `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: partner })}`;
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space id and chat query params
    goto(url);
  }
</script>

<Select.Root type="single" value={chat.partner.id} onValueChange={openPartner}>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        in:fly|global={{ x: -5, duration: parent ? 300 : 0, easing: quadInOut, opacity: 0.3 }}
        class="group text-primary hover:border-dimmer hover:bg-hover-default flex max-w-[calc(100%_-_1rem)] items-center justify-between gap-2 overflow-hidden rounded-lg border border-transparent py-0.5 pr-1 pl-2 text-[1.4rem] leading-normal font-extrabold"
      >
        <span class="truncate">{chat.partner.name}</span>
        <!-- translate-y to make it look on the same line as the chevron in the space selector -->
        <IconChevronUpDown
          class="text-secondary group-hover:text-primary min-w-6 translate-y-[0.05rem]"
        />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content align="start" class="min-w-[24vw]">
    <Select.Group>
      <Select.GroupHeading>{m.select_an_assistant()}</Select.GroupHeading>
      {#each $currentSpace.applications.chat as partner (partner.id)}
        <Select.Item value={partner.id} label={partner.name} class="min-h-12 gap-3">
          <div class="relative flex-shrink-0">
            {#if getIconUrl(partner)}
              <div class="h-10 w-10 overflow-hidden rounded-lg">
                <img src={getIconUrl(partner)} alt="" class="h-full w-full object-cover" />
              </div>
              {#if partner.type === "group-chat"}
                <div class="group-chat-badge">
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
              <SpaceChip space={{ ...partner, personal: false }}></SpaceChip>
            {/if}
          </div>
          <span class="truncate">{formatEmojiTitle(partner.name)}</span>
        </Select.Item>
      {/each}
    </Select.Group>
  </Select.Content>
</Select.Root>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .group-chat-badge {
    @apply bg-primary border-default text-secondary absolute -right-1.5 -bottom-1.5 flex h-5 w-5 items-center justify-center rounded-full border shadow-sm;
  }
</style>
