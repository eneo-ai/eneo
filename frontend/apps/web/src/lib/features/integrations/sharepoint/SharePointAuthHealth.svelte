<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { classifyMicrosoftAuthError, getMicrosoftAuthGuidanceText } from "./microsoftAuthErrors";

  type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];

  interface Props {
    config: Pick<
      TenantSharePointAppPublic,
      "auth_status" | "last_auth_error" | "last_auth_error_at" | "last_auth_success_at"
    >;
    /** "badge" renders only the status badge, "details" only the explanation; "full" both. */
    variant?: "full" | "badge" | "details";
    class?: string;
  }

  let { config, variant = "full", class: className = "" }: Props = $props();

  let status = $derived(config.auth_status ?? "unknown");
  let guidance = $derived(classifyMicrosoftAuthError(config.last_auth_error));
  let showBadge = $derived(variant !== "details");
  let showDetails = $derived(variant !== "badge");

  function formatTime(value: string | null | undefined): string | null {
    if (!value) return null;
    return Number.isNaN(new Date(value).getTime()) ? value : formatDateTime(value);
  }

  let timeline = $derived(
    [
      status === "error" && formatTime(config.last_auth_error_at)
        ? m.sharepoint_auth_last_error_at({ time: formatTime(config.last_auth_error_at) ?? "" })
        : null,
      formatTime(config.last_auth_success_at)
        ? m.sharepoint_auth_last_success({ time: formatTime(config.last_auth_success_at) ?? "" })
        : null
    ].flatMap((entry) => (entry ? [String(entry)] : []))
  );
</script>

{#if showBadge}
  {#if status === "ok"}
    <Badge class="bg-positive-dimmer text-positive-stronger border-transparent {className}">
      {m.sharepoint_auth_status_ok()}
    </Badge>
  {:else if status === "error"}
    <Badge class="bg-negative-dimmer text-negative-stronger border-transparent {className}">
      {m.sharepoint_auth_status_error()}
    </Badge>
  {:else}
    <Badge variant="outline" class={className}>{m.sharepoint_auth_status_unknown()}</Badge>
  {/if}
{/if}

{#if showDetails && (status === "error" || timeline.length > 0)}
  <div
    class="flex flex-col gap-1 rounded-md px-3 py-2 text-xs {status === 'error'
      ? 'bg-negative-dimmer/40'
      : 'bg-secondary'} {variant === 'details' ? className : ''}"
  >
    {#if status === "error" && config.last_auth_error}
      {#if guidance}
        <p class="text-primary text-sm">{getMicrosoftAuthGuidanceText(guidance)}</p>
        <details>
          <summary class="text-secondary cursor-pointer hover:underline">
            {m.sharepoint_auth_error_details()}
          </summary>
          <p class="text-secondary mt-1 font-mono break-words">{config.last_auth_error}</p>
        </details>
      {:else}
        <p class="text-primary text-sm break-words">{config.last_auth_error}</p>
      {/if}
    {/if}
    {#if timeline.length > 0}
      <p class="text-secondary">{timeline.join(" · ")}</p>
    {/if}
  </div>
{/if}
