<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "@intric/ui";
  import { derived } from "svelte/store";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const members = derived(currentSpace, ($currentSpace) => {
    if ($currentSpace.members.length > 4) {
      const members = $currentSpace.members.slice(0, 3);
      return [
        ...members,
        {
          label: "+" + ($currentSpace.members.length - 3)
        }
      ];
    }
    return $currentSpace.members;
  });
</script>

{#if $members.length > 0}
  <Button
    unstyled
    class="hover:bg-hover-default -mr-2 flex cursor-pointer rounded-lg p-2 pl-4"
    href="/spaces/{$currentSpace.routeId}/members"
    aria-label={m.go_to_members_page_for_this_space()}
  >
    {#each $members as member (member)}
      <MemberChip {member}></MemberChip>
    {/each}
  </Button>
{/if}
