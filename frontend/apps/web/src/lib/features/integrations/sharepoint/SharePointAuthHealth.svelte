<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { classifyMicrosoftAuthError, type MicrosoftAuthGuidance } from "./microsoftAuthErrors";

  type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];

  interface Props {
    config: Pick<
      TenantSharePointAppPublic,
      "auth_status" | "last_auth_error" | "last_auth_error_at" | "last_auth_success_at"
    >;
    class?: string;
  }

  let { config, class: className = "" }: Props = $props();

  let status = $derived(config.auth_status ?? "unknown");
  let guidance = $derived(classifyMicrosoftAuthError(config.last_auth_error));

  function formatTime(value: string | null | undefined): string | null {
    if (!value) return null;
    return Number.isNaN(new Date(value).getTime()) ? value : formatDateTime(value);
  }

  function getGuidanceText(kind: MicrosoftAuthGuidance): string {
    switch (kind) {
      case "invalid_client":
        return m.sharepoint_auth_guidance_invalid_client();
      case "interaction_required":
        return m.sharepoint_auth_guidance_interaction_required();
      case "invalid_grant":
        return m.sharepoint_auth_guidance_invalid_grant();
    }
  }
</script>

<div class="flex flex-col gap-1 text-xs {className}">
  {#if status === "ok"}
    <Badge class="bg-positive-dimmer text-positive-stronger w-fit border-transparent">
      {m.sharepoint_auth_status_ok()}
    </Badge>
  {:else if status === "error"}
    <Badge class="bg-negative-dimmer text-negative-stronger w-fit border-transparent">
      {m.sharepoint_auth_status_error()}
    </Badge>
  {:else}
    <Badge variant="outline" class="w-fit">{m.sharepoint_auth_status_unknown()}</Badge>
  {/if}

  {#if status === "error" && config.last_auth_error}
    <div class="text-negative-stronger" role="status">
      {#if guidance}
        <p>{getGuidanceText(guidance)}</p>
        <details class="mt-1">
          <summary class="cursor-pointer hover:underline">
            {m.sharepoint_auth_error_details()}
          </summary>
          <p class="text-secondary mt-1 break-words">{config.last_auth_error}</p>
        </details>
      {:else}
        <p class="break-words">{config.last_auth_error}</p>
      {/if}
    </div>
  {/if}

  {#if status === "error" && formatTime(config.last_auth_error_at)}
    <p class="text-secondary">
      {m.sharepoint_auth_last_error_at({ time: formatTime(config.last_auth_error_at) ?? "" })}
    </p>
  {/if}
  {#if formatTime(config.last_auth_success_at)}
    <p class="text-secondary">
      {m.sharepoint_auth_last_success({ time: formatTime(config.last_auth_success_at) ?? "" })}
    </p>
  {/if}
</div>
