<script>
  import { IconNotification } from "@intric/icons/notification";
  import { IconNotificationDot } from "@intric/icons/notification-dot";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import JobManagerDropdownPanel from "./JobManagerDropdownPanel.svelte";
  import { getJobManager } from "../JobManager";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentlyRunningJobs, showJobManagerPanel }
  } = getJobManager();
  const {
    state: { hasUrgent: hasUrgentKeys, hasWarning: hasWarningKeys }
  } = getExpiringKeysStore();
</script>

<Popover.Root bind:open={$showJobManagerPanel}>
  <Popover.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon-lg" aria-label={m.notifications()}>
        {#if $currentlyRunningJobs === 0 && !$hasUrgentKeys && !$hasWarningKeys}
          <IconNotification />
        {:else if $hasUrgentKeys}
          <IconNotificationDot class="min-w-6" style="--dot-color: var(--color-negative-default)" />
        {:else if $hasWarningKeys}
          <IconNotificationDot class="min-w-6" style="--dot-color: var(--color-warning-default)" />
        {:else}
          <IconNotificationDot class="min-w-6" />
        {/if}
      </Button>
    {/snippet}
  </Popover.Trigger>

  <Popover.Content
    align="end"
    class="flex max-h-[70vh] w-[24rem] flex-col gap-0 overflow-y-auto p-0"
  >
    <p
      class="border-default text-secondary border-b px-4 pt-2 pb-2.5 font-mono text-[0.85rem] font-medium tracking-[0.015rem]"
    >
      {m.notifications_and_jobs()}
    </p>
    <div class="p-2">
      <JobManagerDropdownPanel />
    </div>
  </Popover.Content>
</Popover.Root>
