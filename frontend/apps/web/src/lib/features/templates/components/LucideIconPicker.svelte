<script lang="ts">
  import { Dialog, Button } from "@eneo/ui";
  import {
    loadLucideIcons,
    toKebabCase,
    toPascalCase,
    type LucideIconRegistry
  } from "../lucideIcons";
  import { Search, X, Sparkles, Check } from "lucide-svelte";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  let {
    value = $bindable(null),
    compact = false
  }: {
    value?: string | null;
    compact?: boolean;
  } = $props();

  const dialogOpen = writable(false);
  let searchQuery = $state("");

  // Popular/recommended icons to show first
  const popularIcons = [
    "Rocket",
    "Sparkles",
    "Zap",
    "Star",
    "Heart",
    "MessageSquare",
    "Mail",
    "Bell",
    "Calendar",
    "Clock",
    "User",
    "Users",
    "Building",
    "Home",
    "Briefcase",
    "ShoppingCart",
    "CreditCard",
    "DollarSign",
    "FileText",
    "Image",
    "Video",
    "Music",
    "Code",
    "Database"
  ];

  // The full registry is large, so it is fetched only when the picker opens
  // or a chosen icon has to be shown (see lucideIcons.ts).
  let icons = $state<LucideIconRegistry | null>(null);
  $effect(() => {
    if (icons || (!value && !$dialogOpen)) return;
    void loadLucideIcons().then(
      (registry) => (icons = registry),
      () => {
        // Leave the picker empty; the registry retries on the next open.
      }
    );
  });

  // All available Lucide icon names
  const allIcons = $derived(
    icons
      ? Object.keys(icons)
          .filter((name) => name !== "Icon" && name !== "icons" && !name.startsWith("Lucide"))
          .sort()
      : []
  );

  // Filter icons based on search query
  const filteredIcons = $derived(
    searchQuery
      ? allIcons.filter((iconName) => iconName.toLowerCase().includes(searchQuery.toLowerCase()))
      : []
  );

  function getIconComponent(name: string) {
    return icons?.[name] ?? null;
  }

  const selectedIconComponent = $derived.by(() => {
    if (!value) return null;
    return getIconComponent(toPascalCase(value));
  });

  function handleIconClick(iconName: string) {
    const kebabName = toKebabCase(iconName);
    value = kebabName;
    dialogOpen.set(false);
    searchQuery = "";
  }

  function handleClear() {
    value = null;
  }
</script>

{#if compact}
  <!-- Compact mode: Icon button only (for inline placement) -->
  <button
    type="button"
    onclick={() => dialogOpen.set(true)}
    class="flex h-11 w-11 items-center justify-center rounded-lg border transition-colors
      {value
      ? 'border-strong bg-subtle hover:bg-hover-subtle'
      : 'border-strong bg-component hover:bg-hover-subtle border-dashed'}"
    title={value ? m.change_icon_current({ iconName: value }) : m.choose_icon_optional()}
    aria-label={value ? m.change_icon_current({ iconName: value }) : m.choose_template_icon()}
  >
    {#if selectedIconComponent}
      {@const SelectedIcon = selectedIconComponent}
      <SelectedIcon class="h-5 w-5 text-text" />
    {:else}
      <Sparkles class="text-text-dimmer h-5 w-5" />
    {/if}
  </button>
{:else}
  <!-- Full mode: With label and description -->
  <div class="flex flex-col gap-2">
    <div class="text-default text-sm font-medium">{m.choose_icon_optional()}</div>

    <div class="flex gap-2">
      <button
        type="button"
        onclick={() => dialogOpen.set(true)}
        class="border-strong bg-component hover:bg-hover-subtle flex h-10 min-w-10 items-center gap-2 rounded-lg border px-3 transition-colors"
      >
        {#if selectedIconComponent}
          {@const SelectedIcon = selectedIconComponent}
          <SelectedIcon class="h-5 w-5 text-text" />
          <span class="text-text text-sm">{value}</span>
        {:else}
          <Sparkles class="text-text-dimmer h-5 w-5" />
          <span class="text-text-dimmer text-sm">{m.choose_icon()}</span>
        {/if}
      </button>

      {#if value}
        <Button variant="outlined" padding="icon" onclick={handleClear}>
          <X class="h-4 w-4" />
        </Button>
      {/if}
    </div>
  </div>
{/if}

<Dialog.Root openController={dialogOpen}>
  <Dialog.Content width="medium" {...{ class: "max-w-2xl" }}>
    <Dialog.Title>{m.choose_an_icon()}</Dialog.Title>
    <Dialog.Description>
      {searchQuery ? m.icons_found({ count: filteredIcons.length }) : m.search_to_find_icon()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-4 p-6">
        <!-- Search input -->
        <div class="relative">
          <input
            type="text"
            bind:value={searchQuery}
            placeholder={m.search_icons()}
            class="border-default bg-primary ring-default w-full rounded-lg border py-2 pr-3 pl-10 focus-within:ring-2 focus-visible:ring-2"
          />
          <Search class="text-text-dimmer absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
        </div>

        <!-- Popular icons (when no search) -->
        {#if !searchQuery}
          <div>
            <h4 class="text-text-dimmer mb-2 text-xs font-medium tracking-wide uppercase">
              {m.popular_icons()}
            </h4>
            <div class="grid grid-cols-4 gap-3 sm:grid-cols-6 md:grid-cols-8">
              {#each popularIcons as iconName (iconName)}
                {@const IconComp = getIconComponent(iconName)}
                {@const kebabName = toKebabCase(iconName)}
                {@const isSelected = value === kebabName}
                <button
                  type="button"
                  onclick={() => handleIconClick(iconName)}
                  class="hover:bg-hover-subtle relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors
                    {isSelected
                    ? 'bg-accent-dimmer border-accent-stronger border-2'
                    : 'border-2 border-transparent'}"
                  title={kebabName}
                  aria-label={m.select_icon({ iconName: kebabName })}
                >
                  {#if IconComp}
                    <IconComp class="h-5 w-5 {isSelected ? 'text-accent-stronger' : 'text-text'}" />
                  {/if}
                  {#if isSelected}
                    <div
                      class="bg-accent-stronger absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full"
                    >
                      <Check class="h-3 w-3 text-white" strokeWidth={3} />
                    </div>
                  {/if}
                </button>
              {/each}
            </div>
          </div>

          <hr class="border-default" />
        {/if}

        <!-- All icons / Search results -->
        {#if searchQuery && filteredIcons.length > 0}
          <div class="border-strong max-h-96 overflow-y-auto rounded-lg border p-3">
            <div class="grid grid-cols-4 gap-3 sm:grid-cols-6 md:grid-cols-8">
              {#each filteredIcons.slice(0, 200) as iconName (iconName)}
                {@const IconComp = getIconComponent(iconName)}
                {@const kebabName = toKebabCase(iconName)}
                {@const isSelected = value === kebabName}
                <button
                  type="button"
                  onclick={() => handleIconClick(iconName)}
                  class="hover:bg-hover-subtle relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors
                    {isSelected
                    ? 'bg-accent-dimmer border-accent-stronger border-2'
                    : 'border-2 border-transparent'}"
                  title={kebabName}
                  aria-label={m.select_icon({ iconName: kebabName })}
                >
                  {#if IconComp}
                    <IconComp class="h-5 w-5 {isSelected ? 'text-accent-stronger' : 'text-text'}" />
                  {/if}
                  {#if isSelected}
                    <div
                      class="bg-accent-stronger absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full"
                    >
                      <Check class="h-3 w-3 text-white" strokeWidth={3} />
                    </div>
                  {/if}
                </button>
              {/each}
            </div>

            {#if filteredIcons.length > 200}
              <div class="text-text-dimmer mt-3 text-center text-xs">
                {m.showing_first_icons({ total: filteredIcons.length })}
              </div>
            {/if}
          </div>
        {:else if searchQuery}
          <div class="text-text-dimmer flex items-center justify-center py-12 text-sm">
            {m.no_icons_found({ query: searchQuery })}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls>
      <Button variant="outlined" onclick={() => dialogOpen.set(false)}>{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style lang="postcss">
  @reference "@eneo/ui/styles";
</style>
