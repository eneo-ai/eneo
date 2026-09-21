<script lang="ts">
  import { onMount } from "svelte";
  import { ChevronRight, LoaderCircle } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { m } from "$lib/paraglide/messages";
  import AuthAlert from "./AuthAlert.svelte";

  interface TenantInfo {
    slug: string;
    name: string;
    display_name: string;
  }

  interface Props {
    onTenantSelect: (slug: string) => void;
    tenants?: TenantInfo[];
  }

  const props: Props = $props();

  const LAST_TENANT_KEY = "eneo:last-tenant";
  const SLUG_PATTERN = /^[a-z0-9-]+$/;

  let tenantList = $state<TenantInfo[]>([]);
  let loading = $state(true);
  let error = $state("");
  let searchQuery = $state("");

  let filteredTenants = $derived(
    searchQuery.trim() === ""
      ? tenantList
      : tenantList.filter((t) =>
          [t.display_name, t.name, t.slug]
            .join(" ")
            .toLowerCase()
            .includes(searchQuery.toLowerCase())
        )
  );

  const resultAnnouncement = $derived.by(() => {
    if (filteredTenants.length === 0) return m.no_organizations_found();
    if (filteredTenants.length === 1) return m.tenant_results_one();
    return m.tenant_results_other({ count: filteredTenants.length });
  });

  $effect(() => {
    const providedTenants = props.tenants ?? [];
    if (providedTenants.length > 0) {
      tenantList = providedTenants;
      loading = false;
    }
  });

  onMount(async () => {
    if (tenantList.length > 0) {
      loading = false;
      autoSelectLastTenant();
      return;
    }

    try {
      const { eneo } = await import("$lib/api/client");
      const data = await eneo.auth.listTenants();
      tenantList = data.tenants || [];
      loading = false;
      autoSelectLastTenant();
    } catch (err) {
      console.error("Failed to load tenants:", err);
      error = m.failed_to_load_organizations();
      loading = false;
    }
  });

  function isValidSlug(slug: string) {
    return SLUG_PATTERN.test(slug) && slug.length <= 63;
  }

  function autoSelectLastTenant() {
    if (tenantList.length === 0) {
      return;
    }

    const lastTenant = localStorage.getItem(LAST_TENANT_KEY);
    if (!lastTenant) {
      return;
    }

    if (isValidSlug(lastTenant) && tenantList.some((t) => t.slug === lastTenant)) {
      props.onTenantSelect(lastTenant);
      return;
    }

    localStorage.removeItem(LAST_TENANT_KEY);
  }

  function handleTenantClick(slug: string) {
    if (!isValidSlug(slug)) {
      error = m.invalid_organization_identifier();
      return;
    }

    localStorage.setItem(LAST_TENANT_KEY, slug);
    props.onTenantSelect(slug);
  }
</script>

{#if loading}
  <div class="flex min-h-48 items-center justify-center" role="status" aria-live="polite">
    <div class="flex flex-col items-center gap-3">
      <LoaderCircle class="text-accent-default size-8 animate-spin" aria-hidden="true" />
      <p class="text-muted text-sm">{m.loading_organizations()}</p>
    </div>
  </div>
{:else if error}
  <AuthAlert tone="error">
    <p>{error}</p>
  </AuthAlert>
  <Button variant="outline" class="w-full" onclick={() => window.location.reload()}>
    {m.retry()}
  </Button>
{:else if tenantList.length === 0}
  <p class="text-muted py-6 text-center">{m.no_organizations_available()}</p>
{:else}
  <Field.Field>
    <Field.Label for="tenant-search">{m.search_organizations()}</Field.Label>
    <Input
      id="tenant-search"
      type="search"
      bind:value={searchQuery}
      placeholder={m.search_by_name_or_municipality()}
      autocomplete="off"
      aria-controls="tenant-list"
      class="h-10"
    />
  </Field.Field>

  <p class="sr-only" aria-live="polite">{resultAnnouncement}</p>

  <div id="tenant-list">
    {#if filteredTenants.length === 0}
      <div class="flex flex-col items-center gap-1 py-8 text-center">
        <p class="font-medium">{m.no_organizations_found()}</p>
        <p class="text-muted text-sm">{m.try_different_search_term()}</p>
      </div>
    {:else}
      <ul
        class="border-default flex max-h-96 flex-col gap-1 overflow-y-auto rounded-lg border p-1"
        aria-label={m.select_your_organization()}
      >
        {#each filteredTenants as tenant (tenant.slug)}
          <li>
            <button
              type="button"
              class="hover:bg-hover-default focus-visible:ring-ring flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-left transition-colors outline-none focus-visible:ring-2"
              onclick={() => handleTenantClick(tenant.slug)}
            >
              <span class="flex min-w-0 flex-col">
                <span class="truncate font-medium">{tenant.display_name}</span>
                <span class="text-muted truncate text-sm">{tenant.name}</span>
              </span>
              <ChevronRight class="text-muted size-4 shrink-0" aria-hidden="true" />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
