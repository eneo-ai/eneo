<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import MemberChip from "./MemberChip.svelte";
  import { m } from "$lib/paraglide/messages";

  export let members: { id: string; email: string; role: string }[] = [];
</script>

{#if members.length > 0}
  <div class="flex">
    {#each members.slice(0, 3) as member (member.id)}
      <MemberChip {member}></MemberChip>
    {/each}
    {#if members.length > 3}
      <div class="ml-2 flex items-center justify-center">
        {m.spaces_more_members({ count: members.length - 3 })}
      </div>
    {/if}
  </div>
{/if}
