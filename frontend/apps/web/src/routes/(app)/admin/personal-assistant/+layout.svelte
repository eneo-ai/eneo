<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { page } from "$app/stores";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages";
  import { SlidersHorizontal } from "lucide-svelte";

  let { children } = $props();

  const currentPath = $derived($page.url.pathname);

  // href values stay as RouteId literals so `resolve()` keeps its type-narrowed
  // route check at the call site; `matches` reuses the same literal for the
  // active-tab comparison.
  const tabs = $derived([
    {
      href: "/admin/personal-assistant/configuration",
      label: m.governance_tab_configuration(),
      hint: m.governance_tab_configuration_hint(),
      icon: SlidersHorizontal,
      matches: (p: string) => p.startsWith(resolve("/admin/personal-assistant/configuration"))
    }
  ] as const);
</script>

<div class="flex h-full min-w-0 flex-grow flex-col overflow-hidden">
  <div class="border-default bg-primary border-b">
    <div class="px-6 pt-5 pb-3">
      <h1 class="text-primary text-xl font-bold">{m.governance_title()}</h1>
      <p class="text-secondary mt-0.5 text-sm">
        {m.governance_subtitle()}
      </p>
    </div>
    <nav aria-label={m.governance_subsections_aria()} class="px-6">
      <ul class="-mb-px flex items-end gap-1">
        {#each tabs as tab (tab.href)}
          {@const active = tab.matches(currentPath)}
          <li>
            <a
              href={resolve(tab.href)}
              aria-current={active ? "page" : undefined}
              class="group focus-visible:ring-ring relative flex items-center gap-2 rounded-t-md border-b-2 px-4 py-2.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none
                {active
                ? 'border-accent-default text-primary'
                : 'text-secondary hover:text-primary hover:border-default border-transparent'}"
            >
              <tab.icon
                class="h-4 w-4 transition-colors {active ? 'text-accent-default' : ''}"
                aria-hidden="true"
              />
              <span>{tab.label}</span>
              <span class="text-tertiary hidden text-xs font-normal lg:inline">· {tab.hint}</span>
            </a>
          </li>
        {/each}
      </ul>
    </nav>
  </div>
  <div class="flex min-h-0 flex-1 flex-col overflow-auto">
    {@render children?.()}
  </div>
</div>
