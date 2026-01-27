<script lang="ts">
  import type { Integration, UserIntegration } from "@intric/intric-js";
  import type { Snippet } from "svelte";
  import IntegrationVendorIcon from "./IntegrationVendorIcon.svelte";
  import { integrationData } from "../IntegrationData";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    integration: Omit<Integration, "id"> | UserIntegration;
    action: Snippet;
  };

  let { integration, action }: Props = $props();

  const descriptionKey = $derived(integrationData[integration.integration_type].descriptionKey);
  const description = $derived(m[descriptionKey as keyof typeof m]?.() ?? descriptionKey);
  const name = $derived(integrationData[integration.integration_type].displayName);

  // Check if integration has auth_type property (UserIntegration)
  const authType = $derived('auth_type' in integration ? integration.auth_type : undefined);

  // Check if tenant app is configured (for SharePoint user_oauth integrations)
  const isTenantAppConfigured = $derived(
    'tenant_app_configured' in integration ? integration.tenant_app_configured !== false : true
  );
</script>

<div
  class="border-default flex flex-col overflow-y-auto rounded-lg border p-4 shadow-md hover:shadow-lg {!isTenantAppConfigured ? 'opacity-60' : ''}"
>
  <div
    class="from-accent-dimmer -mx-4 -mt-4 bg-gradient-to-b to-[var(--background-primary)] px-4 pt-4"
  >
    <div class="border-default bg-primary -ml-0.5 w-fit rounded-lg border p-2 shadow-md">
      <IntegrationVendorIcon size="lg" type={integration.integration_type}></IntegrationVendorIcon>
    </div>
  </div>
  <div class="flex flex-col gap-1 pt-4 pb-4">
    <div class="flex items-center gap-2">
      <h2 class="text-2xl font-extrabold">{name}</h2>
      {#if authType === "tenant_app"}
        <span class="text-accent-stronger bg-accent-dimmer border-accent-default rounded px-1.5 py-0.5 text-xs font-semibold border">
          Organization
        </span>
      {:else if authType === "user_oauth"}
        <span class="text-secondary bg-dimmer border-default rounded px-1.5 py-0.5 text-xs font-semibold border">
          Personal
        </span>
      {/if}
    </div>
    <p class=" text-secondary">
      {description}
    </p>
  </div>
  <div class="h-1 flex-grow"></div>
  {@render action()}
</div>
