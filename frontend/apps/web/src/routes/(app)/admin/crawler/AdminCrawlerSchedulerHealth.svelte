<script lang="ts">
  import dayjs from "dayjs";
  import type { AdminCrawlerSchedulerHealth } from "@eneo/eneo-js";
  import { CircleCheck, CircleHelp, CircleX, TriangleAlert } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    scheduler,
    asOf
  }: { scheduler: AdminCrawlerSchedulerHealth | null | undefined; asOf: string | undefined } =
    $props();

  const status = $derived(scheduler?.status);
  const label = $derived(
    status === "ok"
      ? m.admin_crawler_scheduler_ok()
      : status === "degraded"
        ? m.admin_crawler_scheduler_degraded()
        : status === "stale"
          ? m.admin_crawler_scheduler_stale()
          : m.admin_crawler_scheduler_unknown()
  );
  const help = $derived(
    status === "degraded"
      ? m.admin_crawler_scheduler_help_degraded()
      : status === "stale"
        ? m.admin_crawler_scheduler_help_stale()
        : status === "unknown"
          ? m.admin_crawler_scheduler_help_unknown()
          : null
  );

  function lastRun(ranAt: string) {
    const at = dayjs(ranAt);
    const sameDay = at.isSame(asOf ? dayjs(asOf) : dayjs(), "day");
    return at.format(sameDay ? "HH:mm" : "YYYY-MM-DD HH:mm");
  }
</script>

{#if scheduler}
  <div role="group" aria-labelledby="crawler-scheduler" class="flex flex-col gap-1 text-sm">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span id="crawler-scheduler">{m.admin_crawler_scheduler()}</span>
      <Badge
        variant={status === "stale" ? "destructive" : "secondary"}
        class={status === "ok"
          ? "bg-positive-dimmer text-positive-stronger"
          : status === "degraded"
            ? "bg-warning-dimmer text-warning-stronger"
            : undefined}
      >
        {#if status === "ok"}<CircleCheck aria-hidden="true" data-icon="inline-start" />
        {:else if status === "degraded"}<TriangleAlert
            aria-hidden="true"
            data-icon="inline-start"
          />
        {:else if status === "stale"}<CircleX aria-hidden="true" data-icon="inline-start" />
        {:else}<CircleHelp aria-hidden="true" data-icon="inline-start" />{/if}
        {label}
      </Badge>
      {#if status !== "unknown"}
        <span class="text-secondary">
          {m.admin_crawler_scheduler_last_run({
            time: scheduler.ran_at ? lastRun(scheduler.ran_at) : "—"
          })}
        </span>
        {#if scheduler.due != null && scheduler.admitted != null && scheduler.failed != null}
          <span class="text-secondary tabular-nums">
            {m.admin_crawler_scheduler_counts({
              due: scheduler.due,
              admitted: scheduler.admitted,
              failed: scheduler.failed
            })}
          </span>
        {/if}
      {/if}
    </div>
    {#if help}<p class="text-secondary max-w-3xl text-xs leading-5">{help}</p>{/if}
  </div>
{/if}
