<script lang="ts">
  import { User, KeyRound, Building2, LogOut, Sparkles } from "lucide-svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ThemeToggle from "$lib/components/ThemeToggle.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { goto } from "$app/navigation";
  import { browser } from "$app/environment";
  import { getAppContext } from "$lib/core/AppContext";
  import { getWhatsNewStore } from "$lib/features/whats-new/whatsNewStore";

  interface Props {
    tenantFederationEnabled?: boolean;
  }

  const { tenantFederationEnabled = false }: Props = $props();

  const {
    user,
    state: { userInfo }
  } = getAppContext();
  const { hasUnseen, enabled: whatsNewEnabled } = getWhatsNewStore();

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
        aria-label={$hasUnseen
          ? `${m.account_and_settings()} – ${m.whats_new_unseen()}`
          : m.account_and_settings()}
        class="bg-accent-default text-on-fill hover:bg-accent-stronger focus-visible:ring-ring/50 relative flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors focus-visible:ring-3 focus-visible:outline-none"
      >
        {initials}
        {#if $hasUnseen}
          <span
            aria-hidden="true"
            class="bg-positive-default ring-secondary absolute -top-0.5 -right-0.5 size-3 rounded-full ring-2"
          ></span>
        {/if}
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

    {#if $whatsNewEnabled}
      <DropdownMenu.Item>
        {#snippet child({ props })}
          <a {...props} href={localizeHref("/whats-new")}>
            <Sparkles />
            {m.whats_new()}
            {#if $hasUnseen}
              <span aria-hidden="true" class="bg-positive-default ml-auto size-2 rounded-full"
              ></span>
              <span class="sr-only">{m.whats_new_unseen()}</span>
            {/if}
          </a>
        {/snippet}
      </DropdownMenu.Item>
    {/if}
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
        <!-- The logout load clears the session cookies, so hover preloading
             must not run it (hover is enabled on the (app) layout wrapper). -->
        <a {...props} href={localizeHref("/logout")} data-sveltekit-preload-data="false">
          <LogOut />
          {m.logout()}
        </a>
      {/snippet}
    </DropdownMenu.Item>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
  </DropdownMenu.Content>
</DropdownMenu.Root>
