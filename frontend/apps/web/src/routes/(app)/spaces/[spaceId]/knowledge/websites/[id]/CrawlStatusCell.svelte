<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import { getCrawlRunStatus } from "$lib/features/knowledge/crawlStatusPresentation";

  export let crawl: CrawlRun;

  $: status = getCrawlRunStatus(crawl, { compact: true });
</script>

<StatusBadge tone={status.tone} tooltip={status.tooltip}>{status.label}</StatusBadge>
