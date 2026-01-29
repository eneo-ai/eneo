<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import type { UserSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  export let users: UserSparse[] = [];
</script>

{#if users.length > 0}
  <div class="flex items-center">
    {#each users.slice(0, 3) as user (user.id)}
      <MemberChip member={{ ...user, role: "member" }}></MemberChip>
    {/each}
    {#if users.length > 3}
      <span class="text-secondary ml-2 text-sm">
        +{users.length - 3}
      </span>
    {/if}
  </div>
{:else}
  <span class="text-muted text-sm">{m.no_members()}</span>
{/if}
