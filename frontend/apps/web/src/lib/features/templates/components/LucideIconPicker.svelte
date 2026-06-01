<script lang="ts">
  import { Dialog, Button } from "@intric/ui";
  import { Search, X, Sparkles, Check } from "lucide-svelte";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import {
    getTemplateIconComponent,
    templateIconOptions,
    type TemplateIconOption
  } from "$lib/features/templates/templateIconRegistry";

  let {
    value = $bindable(null),
    compact = false
  }: {
    value?: string | null;
    compact?: boolean;
  } = $props();

  const dialogOpen = writable(false);
  let searchQuery = $state("");

  const filteredIcons = $derived(
    searchQuery
      ? templateIconOptions.filter((option) =>
          `${option.name} ${option.value}`.toLowerCase().includes(searchQuery.toLowerCase())
        )
      : []
  );

  const SelectedIconComponent = $derived.by(() => {
    if (!value) return null;
    return getTemplateIconComponent(value);
  });

  function handleIconClick(option: TemplateIconOption) {
    value = option.value;
    dialogOpen.set(false);
    searchQuery = "";
  }

  function handleClear() {
    value = null;
  }
</script>

{#if compact}
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
    {#if SelectedIconComponent}
      <SelectedIconComponent class="text-text h-5 w-5" />
    {:else}
      <Sparkles class="text-text-dimmer h-5 w-5" />
    {/if}
  </button>
{:else}
  <div class="flex flex-col gap-2">
    <div class="text-default text-sm font-medium">{m.choose_icon_optional()}</div>

    <div class="flex gap-2">
      <button
        type="button"
        onclick={() => dialogOpen.set(true)}
        class="border-strong bg-component hover:bg-hover-subtle flex h-10 min-w-10 items-center gap-2 rounded-lg border px-3 transition-colors"
      >
        {#if SelectedIconComponent}
          <SelectedIconComponent class="text-text h-5 w-5" />
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
        <div class="relative">
          <input
            type="text"
            bind:value={searchQuery}
            placeholder={m.search_icons()}
            class="border-default bg-primary ring-default w-full rounded-lg border py-2 pr-3 pl-10 focus-within:ring-2 focus-visible:ring-2"
          />
          <Search class="text-text-dimmer absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
        </div>

        {#if !searchQuery}
          <div>
            <h4 class="text-text-dimmer mb-2 text-xs font-medium tracking-wide uppercase">
              {m.popular_icons()}
            </h4>
            <div class="grid grid-cols-4 gap-3 sm:grid-cols-6 md:grid-cols-8">
              {#each templateIconOptions as option (option.value)}
                {@const IconComp = option.component}
                {@const isSelected = value === option.value}
                <button
                  type="button"
                  onclick={() => handleIconClick(option)}
                  class="hover:bg-hover-subtle relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors
                    {isSelected
                    ? 'bg-accent-dimmer border-accent-stronger border-2'
                    : 'border-2 border-transparent'}"
                  title={option.value}
                  aria-label={m.select_icon({ iconName: option.value })}
                >
                  <IconComp class="h-5 w-5 {isSelected ? 'text-accent-stronger' : 'text-text'}" />
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

        {#if searchQuery && filteredIcons.length > 0}
          <div class="border-strong max-h-96 overflow-y-auto rounded-lg border p-3">
            <div class="grid grid-cols-4 gap-3 sm:grid-cols-6 md:grid-cols-8">
              {#each filteredIcons as option (option.value)}
                {@const IconComp = option.component}
                {@const isSelected = value === option.value}
                <button
                  type="button"
                  onclick={() => handleIconClick(option)}
                  class="hover:bg-hover-subtle relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors
                    {isSelected
                    ? 'bg-accent-dimmer border-accent-stronger border-2'
                    : 'border-2 border-transparent'}"
                  title={option.value}
                  aria-label={m.select_icon({ iconName: option.value })}
                >
                  <IconComp class="h-5 w-5 {isSelected ? 'text-accent-stronger' : 'text-text'}" />
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
