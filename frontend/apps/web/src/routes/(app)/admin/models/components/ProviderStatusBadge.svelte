<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Visual status indicator for a provider connection. The badge can run a real
  connectivity test (`modelProviders.test()`) on demand — clicking the badge
  triggers the test and updates state. We deliberately do NOT auto-run the
  test on mount: every badge in the table would fan-out a paid round-trip to
  the upstream provider on each page load.

  States:
    - `inactive`            — provider has is_active=false
    - `needs_credentials`   — no masked_api_key on record
    - `unknown`             — credentials exist, never tested in this session
    - `testing`             — test in flight
    - `connected`           — test returned success
    - `error`               — test returned a failure
-->

<script lang="ts">
  import type { ModelProviderPublic } from "@intric/intric-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import {
    CheckCircle2,
    AlertCircle,
    XCircle,
    CircleOff,
    HelpCircle,
    Loader2
  } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getIntric } from "$lib/core/Intric";

  type StatusType =
    | "connected"
    | "needs_credentials"
    | "error"
    | "inactive"
    | "unknown"
    | "testing";

  let { provider }: { provider: ModelProviderPublic } = $props();

  const intric = getIntric();

  let testStatus = $state<"idle" | "testing" | "ok" | "failed">("idle");
  let testError = $state<string | null>(null);

  const baseStatus: StatusType = $derived.by(() => {
    if (!provider.is_active) return "inactive";
    if (!provider.masked_api_key || provider.masked_api_key === "") return "needs_credentials";
    return "unknown";
  });

  const status: StatusType = $derived.by(() => {
    if (testStatus === "testing") return "testing";
    if (testStatus === "ok") return "connected";
    if (testStatus === "failed") return "error";
    return baseStatus;
  });

  const config: Record<
    StatusType,
    { variant: "default" | "secondary" | "destructive" | "outline"; icon: typeof CheckCircle2 }
  > = {
    connected: { variant: "outline", icon: CheckCircle2 },
    needs_credentials: { variant: "outline", icon: AlertCircle },
    error: { variant: "destructive", icon: XCircle },
    inactive: { variant: "secondary", icon: CircleOff },
    unknown: { variant: "outline", icon: HelpCircle },
    testing: { variant: "outline", icon: Loader2 }
  };

  const colorOverride: Record<StatusType, string> = {
    // shadcn Badge variants don't carry semantic colour beyond "destructive".
    // We layer our eneo tokens on top so the status hues stay consistent with
    // the rest of the admin surface (positive/warning/dimmer namespaces).
    connected: "border-positive-default/30 bg-positive-dimmer/40 text-positive-stronger",
    needs_credentials: "border-warning-default/30 bg-warning-dimmer/40 text-warning-stronger",
    error: "",
    inactive: "",
    unknown: "border-dimmer bg-surface-dimmer text-muted",
    testing: "border-accent-default/30 bg-accent-dimmer/40 text-accent-stronger"
  };

  function getLabel(s: StatusType): string {
    switch (s) {
      case "connected":
        return m.provider_status_connected();
      case "needs_credentials":
        return m.provider_status_needs_credentials();
      case "error":
        return m.provider_status_error();
      case "inactive":
        return m.provider_status_inactive();
      case "testing":
        return m.testing();
      case "unknown":
        return m.provider_status_unknown();
    }
  }

  function getTooltip(s: StatusType): string {
    switch (s) {
      case "connected":
        return m.provider_status_tooltip_connected({ maskedKey: provider.masked_api_key || "***" });
      case "needs_credentials":
        return m.provider_status_tooltip_needs_credentials();
      case "error":
        return testError ?? m.provider_status_tooltip_error();
      case "inactive":
        return m.provider_status_tooltip_inactive();
      case "testing":
        return m.testing();
      case "unknown":
        return m.provider_status_tooltip_unknown();
    }
  }

  async function runTest(event: MouseEvent) {
    event.stopPropagation();
    if (testStatus === "testing") return;
    if (baseStatus === "needs_credentials" || baseStatus === "inactive") return;

    testStatus = "testing";
    testError = null;
    try {
      const result = (await intric.modelProviders.test({ id: provider.id })) as {
        success?: boolean;
        error?: string;
      };
      if (result?.success) {
        testStatus = "ok";
      } else {
        testStatus = "failed";
        testError = result?.error ?? null;
      }
    } catch (e: unknown) {
      testStatus = "failed";
      testError = e instanceof Error ? e.message : null;
    }
  }

  const Icon = $derived(config[status].icon);
  const variant = $derived(config[status].variant);
  const colorClass = $derived(colorOverride[status]);
  const label = $derived(getLabel(status));
  const tooltipText = $derived(getTooltip(status));
  const canTest = $derived(baseStatus !== "needs_credentials" && baseStatus !== "inactive");
</script>

<Tooltip.Root>
  <Tooltip.Trigger>
    {#snippet child({ props })}
      <Badge
        {variant}
        class={colorClass}
        onclick={canTest ? runTest : undefined}
        role={canTest ? "button" : undefined}
        tabindex={canTest ? 0 : undefined}
        aria-label={canTest ? `${label} — ${m.test_provider_connection()}` : label}
        {...props}
      >
        <Icon class={status === "testing" ? "animate-spin" : ""} />
        <span>{label}</span>
      </Badge>
    {/snippet}
  </Tooltip.Trigger>
  <Tooltip.Content>{tooltipText}</Tooltip.Content>
</Tooltip.Root>
