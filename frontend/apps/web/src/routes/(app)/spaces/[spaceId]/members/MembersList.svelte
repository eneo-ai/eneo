<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import MemberChipStack from "$lib/features/spaces/components/MemberChipStack.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

{#if $currentSpace.members.length > 0}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
  <a
    class="hover:bg-hover-default -mr-2 flex cursor-pointer rounded-lg p-2 pl-4"
    href={localizeHref(`/spaces/${$currentSpace.routeId}/members`)}
    aria-label={m.go_to_members_page_for_this_space()}
  >
    <MemberChipStack members={$currentSpace.members}></MemberChipStack>
  </a>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{/if}
