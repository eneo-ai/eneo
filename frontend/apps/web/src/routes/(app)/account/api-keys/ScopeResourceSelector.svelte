<script lang="ts">
  import { createCombobox } from "@melt-ui/svelte";
  import type { SpaceSparse } from "@intric/intric-js";
  import {
    Search,
    Check,
    ChevronDown,
    Building2,
    MessageSquare,
    AppWindow,
    X
  } from "lucide-svelte";
  import { fly } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  type ResourceType = "space" | "assistant" | "app";
  type Resource = {
    id: string;
    name: string;
    type: ResourceType;
    spaceName?: string;
  };

  type ResourceOption = { id: string; name: string; spaceName?: string };

  let {
    scopeType,
    value = $bindable<string | null>(null),
    spaces = [],
    assistants = [],
    apps = [],
    disabled = false
  } = $props<{
    scopeType: ResourceType;
    value?: string | null;
    spaces?: SpaceSparse[];
    assistants?: ResourceOption[];
    apps?: ResourceOption[];
    disabled?: boolean;
  }>();

  // Build resource list based on scope type
  const resources = $derived.by((): Resource[] => {
    switch (scopeType) {
      case "space":
        return spaces.map(
          (s: SpaceSparse): Resource => ({ id: s.id, name: s.name, type: "space" as const })
        );
      case "assistant":
        return assistants.map(
          (a: ResourceOption): Resource => ({
            id: a.id,
            name: a.name,
            type: "assistant" as const,
            spaceName: a.spaceName
          })
        );
      case "app":
        return apps.map(
          (a: ResourceOption): Resource => ({
            id: a.id,
            name: a.name,
            type: "app" as const,
            spaceName: a.spaceName
          })
        );
      default:
        return [];
    }
  });

  // Find selected resource
  const selectedResource = $derived(resources.find((r: Resource) => r.id === value));

  const {
    elements: { menu, input, option, label },
    states: { open, inputValue, touchedInput },
    helpers: { isSelected }
  } = createCombobox<Resource>({
    forceVisible: true,
    portal: null
  });

  // Filter resources based on search input
  const filteredResources = $derived.by((): Resource[] => {
    if (!$touchedInput || !$inputValue) {
      return resources;
    }
    const query = $inputValue.toLowerCase();
    return resources.filter(
      (r: Resource) =>
        r.name.toLowerCase().includes(query) ||
        r.id.toLowerCase().includes(query) ||
        r.spaceName?.toLowerCase().includes(query)
    );
  });

  // Handle selection
  function handleSelect(resource: Resource) {
    value = resource.id;
    $inputValue = resource.name;
    $open = false;
  }

  // Clear selection
  function clearSelection() {
    value = null;
    $inputValue = "";
  }

  // Get icon for resource type
  function getIcon(type: ResourceType) {
    switch (type) {
      case "space":
        return Building2;
      case "assistant":
        return MessageSquare;
      case "app":
        return AppWindow;
    }
  }

  // Sync inputValue when selection changes externally
  $effect(() => {
    if (selectedResource && !$touchedInput) {
      $inputValue = selectedResource.name;
    }
  });

  // Reset when scope type changes
  $effect(() => {
    if (scopeType) {
      value = null;
      $inputValue = "";
    }
  });

  const Icon = $derived(getIcon(scopeType));
</script>

<div class="relative w-full">
  <span {...$label} class="text-default mb-1.5 block text-sm font-medium">
    {m.api_keys_select_resource({ scopeType })}
  </span>

  <div class="relative">
    <!-- Search Icon -->
    <Search
      class="text-muted pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2"
    />

    <!-- Input -->
    <input
      {...$input}
      use:input
      class="border-default bg-primary placeholder:text-muted hover:border-dimmer focus:border-accent-default focus:ring-accent-default/20 h-11 w-full rounded-lg
             border pr-16 pl-10
             text-sm transition-all duration-150 focus:ring-2
             disabled:cursor-not-allowed disabled:opacity-50"
      placeholder={m.api_keys_search_resource({ scopeType })}
      {disabled}
    />

    <!-- Right side icons -->
    <div class="absolute top-1/2 right-3 flex -translate-y-1/2 items-center gap-1">
      {#if value}
        <button
          type="button"
          onclick={clearSelection}
          class="text-muted hover:bg-hover-default hover:text-default rounded p-1 transition-colors"
          aria-label="Clear selection"
        >
          <X class="h-4 w-4" />
        </button>
      {/if}
      <ChevronDown
        class="text-muted h-4 w-4 transition-transform duration-200 {$open ? 'rotate-180' : ''}"
      />
    </div>
  </div>

  <!-- Selected resource badge -->
  {#if selectedResource}
    <div class="mt-2 flex items-center gap-2">
      <div
        class="border-accent-default/30 bg-accent-default/5 inline-flex items-center gap-2 rounded-lg border px-3 py-1.5"
      >
        <Icon class="text-accent-default h-4 w-4" />
        <span class="text-default text-sm font-medium">{selectedResource.name}</span>
        {#if selectedResource.spaceName}
          <span class="text-muted text-xs">· {selectedResource.spaceName}</span>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Dropdown menu -->
  {#if $open}
    <div
      {...$menu}
      use:menu
      class="border-default bg-primary absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border shadow-lg"
      transition:fly={{ y: -4, duration: 150 }}
    >
      {#if filteredResources.length === 0}
        <div class="px-4 py-8 text-center">
          <div
            class="bg-secondary mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full"
          >
            <Search class="text-muted h-5 w-5" />
          </div>
          <p class="text-muted text-sm">{m.api_keys_no_resource_found({ scopeType })}</p>
          {#if $inputValue}
            <p class="text-muted mt-1 text-xs">{m.api_keys_try_different_search()}</p>
          {/if}
        </div>
      {:else}
        <div class="p-1">
          {#each filteredResources as resource (resource.id)}
            {@const selected = $isSelected(resource)}
            <button
              {...$option({ value: resource, label: resource.name })}
              use:option
              type="button"
              class="hover:bg-hover-default data-[highlighted]:bg-hover-default flex w-full items-center gap-3 rounded-lg px-3 py-2.5
                     text-left
                     transition-colors
                     {selected ? 'bg-accent-default/5' : ''}"
              onclick={() => handleSelect(resource)}
            >
              <!-- Resource type icon -->
              <div
                class="flex h-8 w-8 items-center justify-center rounded-lg
                       {selected
                  ? 'bg-accent-default/15 text-accent-default'
                  : 'bg-secondary text-muted'}"
              >
                <Icon class="h-4 w-4" />
              </div>

              <!-- Resource info -->
              <div class="min-w-0 flex-1">
                <p class="text-default truncate text-sm font-medium">{resource.name}</p>
                {#if resource.spaceName}
                  <p class="text-muted truncate text-xs">
                    {m.api_keys_in_space({ spaceName: resource.spaceName })}
                  </p>
                {:else}
                  <p class="text-muted truncate font-mono text-xs">{resource.id.slice(0, 8)}...</p>
                {/if}
              </div>

              <!-- Selected check -->
              {#if selected}
                <Check class="text-accent-default h-4 w-4 flex-shrink-0" />
              {/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
