<script lang="ts">
  import AuthAlert from "./AuthAlert.svelte";
  import { resolveLoginStatus } from "./loginStatus";

  let { message }: { message: string | null } = $props();

  const status = $derived(resolveLoginStatus(message));
</script>

{#if status}
  <AuthAlert tone={status.tone} title={status.title}>
    <p>{status.description}</p>
    {#if status.reasons}
      <ul class="list-inside list-disc [&:not(:last-child)]:mb-1.5">
        {#each status.reasons as reason (reason)}
          <li>{reason}</li>
        {/each}
      </ul>
    {/if}
    {#if status.footer}
      <p>{status.footer}</p>
    {/if}
  </AuthAlert>
{/if}
