<script lang="ts">
  import LockKeyhole from "@lucide/svelte/icons/lock-keyhole";

  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";

  import type { PageData } from "./$types";
  import FlowRunRetentionPolicyPanel from "./FlowRunRetentionPolicyPanel.svelte";

  type Props = {
    data: PageData;
    onDirtyChange?: (dirty: boolean) => void;
  };

  let { data, onDirtyChange }: Props = $props();

  const policy = $derived(data.flowRunRetentionPolicy);
  const spaceTargets = $derived(data.spaceTargets);
</script>

{#if policy && spaceTargets && (data.access.retentionManage || data.access.retentionHolds)}
  <FlowRunRetentionPolicyPanel
    initialPolicy={policy}
    initialReviewQueue={data.flowRunRetentionReviewQueue}
    initialSpaceTargets={spaceTargets}
    initialHolds={data.flowRetentionHolds}
    initialHoldReviewLimit={data.holdReviewLimit ??
      (data.flowRetentionHolds
        ? { days: data.flowRetentionHolds.review_limit_days, is_default: null }
        : null)}
    canManageRules={data.access.retentionManage}
    canManageHolds={data.access.retentionHolds}
    {onDirtyChange}
  />
{:else}
  <div class="mx-auto w-full max-w-[1180px] px-6 pt-6 lg:px-4">
    <Alert.Root class="max-w-3xl">
      <LockKeyhole aria-hidden="true" />
      <Alert.Title>{m.flow_retention_access_missing_title()}</Alert.Title>
      <Alert.Description>{m.flow_retention_access_missing_description()}</Alert.Description>
    </Alert.Root>
  </div>
{/if}
