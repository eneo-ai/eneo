<script lang="ts">
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";

  interface Props {
    message?: string;
  }

  const { message }: Props = $props();
</script>

{#if message}
  <div
    class="absolute inset-0 flex flex-col items-center justify-center gap-4"
    role="status"
    aria-live="polite"
    aria-busy="true">
    <EneoWordMark class="text-brand-intric h-8 w-20"></EneoWordMark>
    <IconLoadingSpinner class="animate-spin" aria-hidden="true" />
    <p class="text-dimmer text-sm">{message}</p>
  </div>
{/if}
