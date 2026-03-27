<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconCheck } from "@eneo/icons/check";
  import type { SecurityClassification } from "@eneo/eneo-js";
  import { Tooltip } from "@eneo/ui";

  export let model: { security_classification?: SecurityClassification | null | undefined };
</script>

{#if model.security_classification != null}
  <Tooltip text={model.security_classification.name} placement="top">
    <div class="text-positive-stronger flex h-6 w-16 items-center justify-center">
      <IconCheck></IconCheck>
    </div>
  </Tooltip>
{:else}
  <div class="text-muted flex h-6 w-16 items-center justify-center">
    <IconCancel></IconCancel>
  </div>
{/if}
