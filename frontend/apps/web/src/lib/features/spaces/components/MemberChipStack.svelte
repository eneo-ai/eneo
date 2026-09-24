<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import MemberChip from "./MemberChip.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    members: { id: string; email: string }[];
  };

  const { members }: Props = $props();

  // Collapse only when it hides at least two members: "+1 more" is wider than the chip it replaces.
  const MAX_CHIPS = 4;
  const shown = $derived(members.length > MAX_CHIPS ? members.slice(0, MAX_CHIPS - 1) : members);
  const hiddenCount = $derived(members.length - shown.length);
</script>

{#if members.length > 0}
  <div class="flex items-center">
    {#each shown as member (member.id)}
      <MemberChip {member}></MemberChip>
    {/each}
    <!-- The chips are aria-hidden; this gives screen readers the same members. -->
    <span class="sr-only">{shown.map((member) => member.email).join(", ")}</span>
    {#if hiddenCount > 0}
      <span class="text-secondary ml-2 text-sm">
        {m.spaces_more_members({ count: hiddenCount })}
      </span>
    {/if}
  </div>
{:else}
  <span class="text-muted text-sm">{m.no_members()}</span>
{/if}
