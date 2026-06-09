<script lang="ts">
  import { User, KeyRound, Building2, LogOut } from "lucide-svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ThemeToggle from "$lib/components/ThemeToggle.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { goto } from "$app/navigation";
  import { browser } from "$app/environment";
  import { getAppContext } from "$lib/core/AppContext";

  interface Props {
    tenantFederationEnabled?: boolean;
  }

  const { tenantFederationEnabled = false }: Props = $props();

  const {
    user,
    state: { userInfo }
  } = getAppContext();

  const displayName = $derived(
    $userInfo.displayName?.trim() || `${$userInfo.firstName} ${$userInfo.lastName}`.trim()
  );
  const initials = $derived(
    displayName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );

  function handleSwitchOrganisation() {
    // Clear client-side tenant storage
    if (browser) {
      sessionStorage.removeItem("eneo-last-tenant-slug");
      localStorage.removeItem("eneo:last-tenant");
    }

    // Navigate to endpoint (not a SvelteKit route — server endpoint)
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoint, not a typed route
    goto("/login/switch-organisation");
  }
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        type="button"
        aria-label={m.account_and_settings()}
        class="bg-accent-default text-on-fill hover:bg-accent-stronger focus-visible:ring-ring/50 flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors focus-visible:ring-3 focus-visible:outline-none"
      >
        {initials}
      </button>
    {/snippet}
  </DropdownMenu.Trigger>

  <DropdownMenu.Content align="end" class="w-64">
    <div class="flex flex-col px-2 py-1.5">
      <span class="text-foreground truncate text-sm font-medium">{displayName}</span>
      <span class="text-muted truncate text-xs">{user.email}</span>
    </div>

    <DropdownMenu.Separator />

    <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
    <DropdownMenu.Item>
      {#snippet child({ props })}
        <a {...props} href={localizeHref("/account")}>
          <User />
          {m.my_account()}
        </a>
      {/snippet}
    </DropdownMenu.Item>

    <DropdownMenu.Item>
      {#snippet child({ props })}
        <a {...props} href={localizeHref("/account/api-keys")}>
          <KeyRound />
          {m.my_api_keys()}
        </a>
      {/snippet}
    </DropdownMenu.Item>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->

    {#if tenantFederationEnabled}
      <DropdownMenu.Item onclick={handleSwitchOrganisation}>
        <Building2 />
        {m.oidc_choose_another_org()}
      </DropdownMenu.Item>
    {/if}

    <DropdownMenu.Separator />

    <div class="flex items-center justify-between gap-2 px-2 py-1.5">
      <span class="text-foreground text-sm">{m.theme()}</span>
      <ThemeToggle menu />
    </div>

    <DropdownMenu.Separator />

    <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
    <DropdownMenu.Item variant="destructive">
      {#snippet child({ props })}
        <a {...props} href={localizeHref("/logout")}>
          <LogOut />
          {m.logout()}
        </a>
      {/snippet}
    </DropdownMenu.Item>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
  </DropdownMenu.Content>
</DropdownMenu.Root>
