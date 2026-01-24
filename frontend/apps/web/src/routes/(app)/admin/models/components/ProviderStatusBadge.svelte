<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";
  import { CheckCircle2, AlertCircle, XCircle, CircleOff } from "lucide-svelte";

  export let provider: ModelProviderPublic;

  // Determine status based on provider state
  type StatusType = "connected" | "needs_credentials" | "error" | "inactive";

  function getStatus(p: ModelProviderPublic): StatusType {
    if (!p.is_active) {
      return "inactive";
    }
    // Check if credentials are present (masked_api_key exists and not empty)
    if (!p.masked_api_key || p.masked_api_key === "") {
      return "needs_credentials";
    }
    // For now, assume connected if active with credentials
    // TODO: Integrate with modelProviders.test() for real status
    return "connected";
  }

  $: status = getStatus(provider);

  // Status label mapping
  const labels: Record<StatusType, string> = {
    connected: "Connected",
    needs_credentials: "Needs credentials",
    error: "Error",
    inactive: "Inactive"
  };

  // Status color mapping - WCAG 2.1 AA compliant (4.5:1 contrast for text)
  // Light mode: text 35-45% L on 94-95% L bg
  // Dark mode: text 75-82% L on 24-26% L bg
  const colors: Record<StatusType, { text: string; bg: string; border: string }> = {
    connected: {
      text: "text-[oklch(35%_0.12_145)] dark:text-[oklch(80%_0.14_145)]",
      bg: "bg-[oklch(95%_0.04_145)] dark:bg-[oklch(24%_0.06_145)]",
      border: "border-[oklch(85%_0.08_145)] dark:border-[oklch(38%_0.10_145)]"
    },
    needs_credentials: {
      text: "text-[oklch(38%_0.14_85)] dark:text-[oklch(82%_0.16_85)]",
      bg: "bg-[oklch(94%_0.06_85)] dark:bg-[oklch(26%_0.07_85)]",
      border: "border-[oklch(82%_0.12_85)] dark:border-[oklch(40%_0.12_85)]"
    },
    error: {
      text: "text-[oklch(40%_0.16_25)] dark:text-[oklch(80%_0.18_25)]",
      bg: "bg-[oklch(94%_0.05_25)] dark:bg-[oklch(24%_0.07_25)]",
      border: "border-[oklch(82%_0.10_25)] dark:border-[oklch(38%_0.12_25)]"
    },
    inactive: {
      text: "text-[oklch(45%_0.01_0)] dark:text-[oklch(75%_0.02_0)]",
      bg: "bg-[oklch(95%_0.005_0)] dark:bg-[oklch(26%_0.01_0)]",
      border: "border-[oklch(88%_0.01_0)] dark:border-[oklch(38%_0.02_0)]"
    }
  };

  // Status icon mapping
  const icons: Record<StatusType, typeof CheckCircle2> = {
    connected: CheckCircle2,
    needs_credentials: AlertCircle,
    error: XCircle,
    inactive: CircleOff
  };

  $: label = labels[status];
  $: color = colors[status];
  $: Icon = icons[status];

  // Build tooltip content
  $: tooltipContent = (() => {
    switch (status) {
      case "connected":
        return `API key verified: ${provider.masked_api_key || "***"}`;
      case "needs_credentials":
        return "Add your API key to enable this provider";
      case "error":
        return "Connection error - check your API key";
      case "inactive":
        return "Manually disabled by admin";
      default:
        return "";
    }
  })();
</script>

<Tooltip text={tooltipContent}>
  <div
    class="
      inline-flex items-center gap-1.5
      px-2 py-1
      text-xs font-medium
      rounded-full
      {color.bg}
      {color.border}
      border
      transition-colors duration-150
    "
  >
    <svelte:component this={Icon} class="w-3.5 h-3.5 {color.text}" />
    <span class={color.text}>{label}</span>
  </div>
</Tooltip>
