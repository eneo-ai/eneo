<script lang="ts">
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
</script>

<div class="absolute inset-0 flex flex-col items-center justify-center gap-4">
  <EneoWordMark class="text-brand-intric h-8 w-20"></EneoWordMark>
  <IconLoadingSpinner class="animate-spin" />
</div>
