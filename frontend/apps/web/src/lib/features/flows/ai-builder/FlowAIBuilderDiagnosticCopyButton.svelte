<script lang="ts">
  import { onDestroy } from "svelte";
  import { IconCheck } from "@eneo/icons/check";
  import { IconCopy } from "@eneo/icons/copy";
  import { Button, type ButtonSize, type ButtonVariant } from "$lib/components/ui/button/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import {
    formatAIBuilderDiagnosticReport,
    type AIBuilderDiagnosticReport
  } from "./aiBuilderDiagnosticReport";

  interface Props {
    report?: AIBuilderDiagnosticReport | null;
    buildReport?: () => AIBuilderDiagnosticReport | null;
    label?: string;
    variant?: ButtonVariant;
    size?: ButtonSize;
    class?: string;
  }

  let {
    report = null,
    buildReport,
    label = m.ai_builder_copy_technical_details(),
    variant = "outline",
    size = "sm",
    class: className = ""
  }: Props = $props();

  let copied = $state(false);
  let resetTimer: ReturnType<typeof setTimeout> | null = null;

  onDestroy(() => {
    if (resetTimer) clearTimeout(resetTimer);
  });

  function showCopiedState() {
    copied = true;
    if (resetTimer) clearTimeout(resetTimer);
    resetTimer = setTimeout(() => {
      copied = false;
    }, 1600);
  }

  async function copyReport() {
    const currentReport = buildReport?.() ?? report;
    if (!currentReport) return;
    try {
      await navigator.clipboard.writeText(formatAIBuilderDiagnosticReport(currentReport));
      showCopiedState();
    } catch (error) {
      console.error("Could not copy AI Builder diagnostic report", error);
      toast.error(m.ai_builder_copy_technical_details_failed());
    }
  }
</script>

{#if report || buildReport}
  <Button
    {variant}
    {size}
    class={className}
    aria-label={label}
    title={label}
    onclick={() => void copyReport()}
  >
    {#if copied}
      <IconCheck class="size-3.5" />
      <span>{m.copied()}</span>
    {:else}
      <IconCopy class="size-3.5" />
      <span>{label}</span>
    {/if}
  </Button>
{/if}
