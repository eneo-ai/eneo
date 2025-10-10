<script lang="ts">
  import { onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";

  interface TenantInfo {
    slug: string;
    name: string;
    display_name: string;
  }

  interface Props {
    onTenantSelect: (slug: string) => void;
    baseUrl: string;
  }

  let { onTenantSelect, baseUrl }: Props = $props();

  let tenants = $state<TenantInfo[]>([]);
  let loading = $state(true);
  let error = $state("");

  onMount(async () => {
    try {
      // Fetch tenants from backend
      const response = await fetch(`${baseUrl}/api/v1/auth/tenants`);

      if (!response.ok) {
        throw new Error("Failed to fetch tenants");
      }

      const data = await response.json();
      tenants = data.tenants || [];

      // Check for last-used tenant in localStorage
      const lastTenant = localStorage.getItem("eneo:last-tenant");
      if (lastTenant) {
        // Validate slug format
        if (/^[a-z0-9-]+$/.test(lastTenant) && lastTenant.length <= 63) {
          // Check if slug exists in tenant list
          if (tenants.some((t) => t.slug === lastTenant)) {
            // Auto-select last tenant
            onTenantSelect(lastTenant);
            return;
          }
        }
        // Clear invalid cached slug
        localStorage.removeItem("eneo:last-tenant");
      }

      loading = false;
    } catch (err) {
      console.error("Failed to load tenants:", err);
      error = m.failed_to_load_organizations();
      loading = false;
    }
  });

  function handleTenantClick(slug: string) {
    // Validate slug format
    if (!/^[a-z0-9-]+$/.test(slug) || slug.length > 63) {
      error = m.invalid_organization_identifier();
      return;
    }

    // Save to localStorage
    localStorage.setItem("eneo:last-tenant", slug);

    // Notify parent
    onTenantSelect(slug);
  }
</script>

{#if loading}
  <div class="flex min-h-[400px] items-center justify-center">
    <div class="text-center">
      <div
        class="border-accent-default mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2"
      ></div>
      <p class="text-dimmer">{m.loading_organizations()}</p>
    </div>
  </div>
{:else if error}
  <div class="flex min-h-[400px] items-center justify-center">
    <div class="max-w-md text-center">
      <div class="text-negative-default mb-4">
        <svg class="mx-auto h-16 w-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
      </div>
      <p class="text-default mb-4">{error}</p>
      <Button variant="primary" onclick={() => window.location.reload()}>
        {m.retry()}
      </Button>
    </div>
  </div>
{:else if tenants.length === 0}
  <div class="flex min-h-[400px] items-center justify-center">
    <div class="max-w-md text-center">
      <p class="text-dimmer">{m.no_organizations_available()}</p>
    </div>
  </div>
{:else}
  <div class="mx-auto max-w-6xl px-4 py-8">
    <h2 class="text-default mb-6 text-center text-2xl font-semibold">
      {m.select_your_organization()}
    </h2>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each tenants as tenant}
        <button
          class="border-default hover:border-accent-default rounded-lg border-2 p-6 text-left transition-all hover:shadow-lg"
          onclick={() => handleTenantClick(tenant.slug)}
        >
          <h3 class="text-default mb-2 text-lg font-semibold">
            {tenant.display_name}
          </h3>
          <p class="text-dimmer text-sm">
            {tenant.name}
          </p>
        </button>
      {/each}
    </div>
  </div>
{/if}
