<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  interface Props {
    tokens: number;
    highThreshold?: number;
    mediumThreshold?: number;
  }

  const { tokens, highThreshold = 500_000, mediumThreshold = 50_000 }: Props = $props();

  // Determine usage intensity based on total token consumption
  const usageLevel = $derived.by(() => {
    if (tokens > highThreshold) {
      return {
        intensity: m.usage_level_high(),
        badgeClass: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
      };
    } else if (tokens > mediumThreshold) {
      return {
        intensity: m.usage_level_medium(),
        badgeClass: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300"
      };
    } else {
      return {
        intensity: m.usage_level_low(),
        badgeClass: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
      };
    }
  });
</script>

<span
  class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {usageLevel.badgeClass}"
>
  {usageLevel.intensity}
</span>
