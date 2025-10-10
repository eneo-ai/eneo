<script lang="ts">
  import { onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { Button, Input } from "@intric/ui";

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
  let searchQuery = $state("");

  let filteredTenants = $derived(
    searchQuery.trim() === ""
      ? tenants
      : tenants.filter((t) =>
          [t.display_name, t.name, t.slug]
            .join(" ")
            .toLowerCase()
            .includes(searchQuery.toLowerCase())
        )
  );

  onMount(async () => {
    try {
      // Dynamic import to avoid SSR issues
      const { intric } = await import("$lib/api/client");

      // Fetch tenants from backend
      const data = await intric.auth.listTenants();
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
  <div class="mx-auto max-w-md px-4 py-8">
    <h2 class="text-primary mb-6 text-center text-xl font-medium sm:text-2xl">
      {m.select_your_organization()}
    </h2>

    <div class="mb-4">
      <Input.Text
        bind:value={searchQuery}
        label={m.search_organizations()}
        placeholder={m.search_by_name_or_municipality()}
        autocomplete="off"
        hiddenLabel={false}
        inputClass="text-base"
      />
    </div>

    <div class="border-default bg-primary flex max-h-96 flex-col gap-2 overflow-y-auto rounded-lg border p-3 shadow-md">
      {#if filteredTenants.length === 0}
        <div class="flex flex-col items-center gap-3 py-8 text-center">
          <div class="text-primary text-base font-medium">
            {m.no_organizations_found()}
          </div>
          <div class="text-muted text-sm">
            {m.try_different_search_term()}
          </div>
        </div>
      {:else}
        {#each filteredTenants as tenant}
          <button
            class="border-default hover:border-accent-default focus-visible:border-accent-default hover:bg-secondary text-primary flex w-full items-center justify-between rounded-md border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-default focus-visible:ring-offset-2"
            onclick={() => handleTenantClick(tenant.slug)}
          >
            <div class="flex flex-col gap-1">
              <span class="text-primary text-base font-medium">
                {tenant.display_name}
              </span>
              <span class="text-muted text-sm">
                {tenant.name}
              </span>
            </div>
          </button>
        {/each}
      {/if}
    </div>
  </div>
{/if}
