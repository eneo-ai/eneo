<script context="module" lang="ts">
  // Available chart colors for organizations
  const chartColors = [
    "chart-green",
    "chart-moss",
    "chart-red",
    "chart-intric",
    "chart-yellow",
    "chart-blue",
    "accent-default"
  ];

  // Simple hash function to get a consistent index from a string
  function hashString(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash; // Convert to 32bit integer
    }
    return Math.abs(hash);
  }

  // Get a consistent chart color for any identifier (provider name, org, etc.)
  export function getChartColour(identifier: string | undefined | null): string {
    if (!identifier) return chartColors[0];
    const index = hashString(identifier) % chartColors.length;
    return chartColors[index];
  }
</script>

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";
  import { IconInfo } from "@intric/icons/info";
  import { m } from "$lib/paraglide/messages";

  export let model:
    | CompletionModel
    | EmbeddingModel
    | TranscriptionModel
    | { org: string; nickname: string; name: string; description: string };
  export let size: "card" | "table" = "table";
  /** Controls the description info-button next to the model name.
   *
   *  - `interactive` (default): show a tabbable button with the description.
   *  - `non-tabbable`: show the button but skip it in tab order. Use inside
   *    listbox/combobox options so it does not interrupt arrow-key navigation;
   *    the description is still reachable via hover/click.
   *  - `hidden`: omit the button entirely. Use when this component is rendered
   *    inside another interactive element (e.g. a `<button>`) to avoid
   *    nested-interactive-content accessibility issues.
   */
  export let descriptionMode: "interactive" | "non-tabbable" | "hidden" = "interactive";

  $: showDescriptionButton = descriptionMode !== "hidden";
  $: descriptionTabbable = descriptionMode === "interactive";

  $: displayName = "nickname" in model ? model.nickname : model.name;
  // Description is only worth surfacing when it adds something the visible
  // name doesn't already say.
  $: descriptionText =
    model.description && model.description.trim() && model.description !== displayName
      ? model.description
      : null;
</script>

{#if size === "card"}
  <div class="flex items-center justify-start gap-4">
    <h4 class="text-primary text-2xl leading-6 font-extrabold">
      {displayName}
    </h4>
  </div>
{:else}
  <div class="flex items-center gap-1.5">
    <h4 class="text-primary leading-tight">
      {displayName}
    </h4>
    {#if showDescriptionButton && descriptionText}
      <Tooltip text={descriptionText} asFragment let:trigger>
        {@const tooltipTrigger = trigger[0]}
        <button
          type="button"
          {...tooltipTrigger}
          use:tooltipTrigger.action
          aria-label={m.show_model_info()}
          tabindex={descriptionTabbable ? 0 : -1}
          on:click|stopPropagation
          on:pointerdown|stopPropagation
          class="text-secondary hover:text-primary focus-visible:ring-default focus-visible:ring-offset-primary inline-flex shrink-0 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <IconInfo class="size-4" />
        </button>
      </Tooltip>
    {/if}
  </div>
{/if}
