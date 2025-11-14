<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { IconInfo } from "@intric/icons/info";

  interface Props {
    value: number | null;
    hasChanges?: boolean;
    inheritedDays?: number | null;
    inheritedFrom?: "space" | "tenant" | null;
    labelId?: string;
    descriptionId?: string;
  }

  let {
    value = $bindable(),
    hasChanges = false,
    inheritedDays = null,
    inheritedFrom = null,
    labelId,
    descriptionId
  }: Props = $props();

  // Determine inheritance status
  let showInheritanceStatus = $derived(inheritedDays !== null && inheritedFrom === "space");
  let isFollowingSpace = $derived(value === null || value === inheritedDays);
  let isOverridingSpace = $derived(value !== null && value !== inheritedDays);

  let inheritanceStatusMessage = $derived(() => {
    if (!showInheritanceStatus) return null;
    if (isFollowingSpace) {
      return m.conversation_retention_follows_space({ days: inheritedDays!.toString() });
    }
    if (isOverridingSpace) {
      return m.conversation_retention_overrides_space({ days: inheritedDays!.toString() });
    }
    return null;
  });
</script>

<div class="flex flex-col gap-2">
  <!-- Input field + unit label -->
  <div class="flex items-center gap-2">
    <Input.Number
      bind:value
      min={1}
      max={2555}
      aria-label="Gallring av konversationshistorik i dagar"
      aria-labelledby={labelId}
      aria-describedby={descriptionId}
      class="w-[120px]"
    />
    <span class="text-default-dimmer text-base">dagar</span>
  </div>

  <!-- Inheritance status (assistants only) -->
  {#if showInheritanceStatus && inheritanceStatusMessage()}
    <div class="flex items-center gap-1 text-gray-600">
      <IconInfo class="h-4 w-4 flex-shrink-0" />
      <span class="text-xs">{inheritanceStatusMessage()}</span>
    </div>
  {/if}
</div>
