<script lang="ts">
  import * as LucideIcons from 'lucide-svelte';
  import { Dialog, Button } from '@intric/ui';
  import { Search, X, Sparkles, Check } from 'lucide-svelte';
  import { writable } from 'svelte/store';
  import { m } from '$lib/paraglide/messages';

  let {
    value = $bindable(null),
    compact = false
  }: {
    value?: string | null;
    compact?: boolean;
  } = $props();

  const dialogOpen = writable(false);
  let searchQuery = $state('');

  // Popular/recommended icons to show first
  const popularIcons = [
    'Rocket', 'Sparkles', 'Zap', 'Star', 'Heart', 'MessageSquare',
    'Mail', 'Bell', 'Calendar', 'Clock', 'User', 'Users',
    'Building', 'Home', 'Briefcase', 'ShoppingCart', 'CreditCard', 'DollarSign',
    'FileText', 'Image', 'Video', 'Music', 'Code', 'Database'
  ];

  // Get all available Lucide icon names
  const allIcons = Object.keys(LucideIcons)
    .filter(name => name !== 'Icon' && name !== 'icons' && !name.startsWith('Lucide'))
    .sort();

  // Convert PascalCase to kebab-case for storage
  function toKebabCase(str: string): string {
    return str.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
  }

  // Convert kebab-case back to PascalCase for icon lookup
  function toPascalCase(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1).replace(/-([a-z])/g, (g) => g[1].toUpperCase());
  }

  // Filter icons based on search query
  const filteredIcons = $derived(searchQuery
    ? allIcons.filter(iconName =>
        iconName.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : []);

  const selectedIconComponent = $derived.by(() => {
    if (!value) return null;
    const pascalName = toPascalCase(value);
    return (LucideIcons as any)[pascalName] || null;
  });

  function handleIconClick(iconName: string) {
    const kebabName = toKebabCase(iconName);
    value = kebabName;
    dialogOpen.set(false);
    searchQuery = '';
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
      {value ? 'border-strong bg-subtle hover:bg-hover-subtle' : 'border-dashed border-strong bg-component hover:bg-hover-subtle'}"
    title={value ? m.change_icon_current({ iconName: value }) : m.choose_icon_optional()}
    aria-label={value ? m.change_icon_current({ iconName: value }) : m.choose_template_icon()}
  >
    {#if selectedIconComponent}
      {@render selectedIconComponent({ class: "h-5 w-5 text-text" })}
    {:else}
      <Sparkles class="text-text-dimmer h-5 w-5" />
    {/if}
  </button>
{:else}
  <!-- Full mode: With label and description -->
  <div class="flex flex-col gap-2">
    <label class="text-sm font-medium text-default">{m.choose_icon_optional()}</label>

    <div class="flex gap-2">
      <button
        type="button"
        onclick={() => dialogOpen.set(true)}
        class="border-strong bg-component hover:bg-hover-subtle flex h-10 min-w-10 items-center gap-2 rounded-lg border px-3 transition-colors"
      >
        {#if selectedIconComponent}
          {@render selectedIconComponent({ class: "h-5 w-5 text-text" })}
          <span class="text-text text-sm">{value}</span>
        {:else}
          <Sparkles class="text-text-dimmer h-5 w-5" />
          <span class="text-text-dimmer text-sm">{m.choose_icon()}</span>
        {/if}
      </button>

      {#if value}
        <Button variant="outlined" padding="icon-only" onclick={handleClear}>
          <X class="h-4 w-4" />
        </Button>
      {/if}
    </div>
  </div>
{/if}

<Dialog.Root openController={dialogOpen}>
  <Dialog.Content width="medium" class="max-w-2xl">
    <Dialog.Title>{m.choose_an_icon()}</Dialog.Title>
    <Dialog.Description>
      {searchQuery
        ? m.icons_found({ count: filteredIcons.length })
        : m.search_to_find_icon()}
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
            autofocus
          />
          <Search class="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-text-dimmer" />
        </div>

        <!-- Popular icons (when no search) -->
        {#if !searchQuery}
          <div>
            <h4 class="text-text-dimmer mb-2 text-xs font-medium uppercase tracking-wide">{m.popular_icons()}</h4>
            <div class="grid grid-cols-4 gap-3 sm:grid-cols-6 md:grid-cols-8">
              {#each popularIcons as iconName}
                {@const IconComp = (LucideIcons as any)[iconName]}
                {@const kebabName = toKebabCase(iconName)}
                {@const isSelected = value === kebabName}
                <button
                  type="button"
                  onclick={() => handleIconClick(iconName)}
                  class="relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-hover-subtle
                    {isSelected ? 'bg-accent-dimmer border-accent-stronger border-2' : 'border-transparent border-2'}"
                  title={kebabName}
                  aria-label={m.select_icon({ iconName: kebabName })}
                >
                  {#if IconComp}
                    {@render IconComp({ class: `h-5 w-5 ${isSelected ? 'text-accent-stronger' : 'text-text'}` })}
                  {/if}
                  {#if isSelected}
                    <div class="bg-accent-stronger absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full">
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
              {#each filteredIcons.slice(0, 200) as iconName}
                {@const IconComp = (LucideIcons as any)[iconName]}
                {@const kebabName = toKebabCase(iconName)}
                {@const isSelected = value === kebabName}
                <button
                  type="button"
                  onclick={() => handleIconClick(iconName)}
                  class="relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-hover-subtle
                    {isSelected ? 'bg-accent-dimmer border-accent-stronger border-2' : 'border-transparent border-2'}"
                  title={kebabName}
                  aria-label={m.select_icon({ iconName: kebabName })}
                >
                  {#if IconComp}
                    {@render IconComp({ class: `h-5 w-5 ${isSelected ? 'text-accent-stronger' : 'text-text'}` })}
                  {/if}
                  {#if isSelected}
                    <div class="bg-accent-stronger absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full">
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
  @reference "@intric/ui/styles";
</style>
