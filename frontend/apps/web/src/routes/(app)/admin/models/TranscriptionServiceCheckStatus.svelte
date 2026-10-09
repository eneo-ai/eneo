<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  A connection check result: a word and an icon in the table row, or a callout
  with the sentence that explains it in the dialog. The wording lives in
  describeCheck; this component only gives each tone its colour and icon.
-->

<script lang="ts">
  import type { TranscriptionServiceCheck } from "@eneo/eneo-js";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import CircleX from "@lucide/svelte/icons/circle-x";
  import Info from "@lucide/svelte/icons/info";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { cn } from "$lib/utils.js";
  import { describeCheck, type CheckTone } from "./transcriptionServiceCheck";

  let { check, callout = false }: { check: TranscriptionServiceCheck; callout?: boolean } =
    $props();

  const icons = { positive: CircleCheck, info: Info, warning: TriangleAlert, negative: CircleX };
  const ink: Record<CheckTone, string> = {
    positive: "text-positive-stronger",
    info: "text-foreground",
    warning: "text-warning-stronger",
    negative: "text-negative-stronger"
  };
  const wash: Record<CheckTone, string> = {
    positive: "border-positive-default/30 bg-positive-dimmer",
    info: "",
    warning: "border-warning-default/30 bg-warning-dimmer",
    negative: "border-negative-default/30 bg-negative-dimmer"
  };

  const summary = $derived(describeCheck(check));
  const Icon = $derived(icons[summary.tone]);
</script>

{#if callout}
  <Alert.Root role="status" class={cn(wash[summary.tone], ink[summary.tone])}>
    <Icon />
    <Alert.Title>{summary.label}</Alert.Title>
    <!-- A wash carries its own deep text colour; the neutral callout keeps the muted one. -->
    <Alert.Description class={summary.tone === "info" ? undefined : "text-current"}>
      {summary.detail}
    </Alert.Description>
  </Alert.Root>
{:else}
  <span
    class={cn("inline-flex items-center gap-1.5 text-sm", ink[summary.tone])}
    title={summary.detail}
  >
    <Icon class="size-4 shrink-0" aria-hidden="true" />
    {summary.label}
  </span>
{/if}
