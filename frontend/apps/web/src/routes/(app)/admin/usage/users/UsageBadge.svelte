<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  interface Props {
    requests: number;
  }

  const { requests }: Props = $props();

  // Determine usage intensity based on request count using semantic theming
  const usageLevel = $derived.by(() => {
    if (requests > 100) {
      return {
        intensity: "High",
        badgeClass: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
      };
    } else if (requests > 20) {
      return {
        intensity: "Medium", 
        badgeClass: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300"
      };
    } else {
      return {
        intensity: "Low",
        badgeClass: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
      };
    }
  });
</script>

<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {usageLevel.badgeClass}">
  {usageLevel.intensity}
</span>