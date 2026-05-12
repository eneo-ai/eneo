<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import StatusBadge, { type StatusTone } from "$lib/components/StatusBadge.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";

  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;

  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());

  const intervalLabels: Record<string, { label: string; tone: StatusTone }> = {
    daily: { tone: "positive", label: m.every_day() },
    every_other_day: { tone: "positive", label: m.every_other_day() },
    weekly: { tone: "positive", label: m.weekly() },
    never: { tone: "neutral", label: m.never() },
    error: { tone: "negative", label: m.not_found() }
  };

  const intervalDays: Record<string, number> = {
    daily: 1,
    every_other_day: 2,
    weekly: 7
  };

  function nextCrawlTooltip(intervalKey: string): string | undefined {
    if (intervalKey === "never") return undefined;

    const days = intervalDays[intervalKey];
    if (!days) return undefined;

    const lastCrawlAt = website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at;
    if (!lastCrawlAt) return m.next_crawl_after_first_run();

    const nextAt = dayjs(lastCrawlAt).add(days, "day");
    const relative = dayjs().to(nextAt);
    const formatted = `${nextAt.format("YYYY-MM-DD HH:mm")} (${relative})`;
    return m.next_crawl_on({ date: formatted });
  }

  $: intervalKey = website.update_interval ?? "error";
  $: intervalLabel = intervalLabels[intervalKey] ?? intervalLabels.error;
  $: tooltip = nextCrawlTooltip(intervalKey);
</script>

<StatusBadge tone={intervalLabel.tone} {tooltip}>
  {intervalLabel.label}
</StatusBadge>
