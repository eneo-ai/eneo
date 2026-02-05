<script lang="ts">
  import { createCombobox, melt } from "@melt-ui/svelte";
  import type { Space, Assistant } from "@intric/intric-js";
  import { Search, Check, ChevronDown, Building2, MessageSquare, AppWindow, X } from "lucide-svelte";
  import { fly } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  type ResourceType = "space" | "assistant" | "app";
  type Resource = {
    id: string;
    name: string;
    type: ResourceType;
    spaceName?: string;
  };

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
    spaces?: Space[];
    assistants?: Assistant[];
    apps?: { id: string; name: string; spaceName?: string }[];
    disabled?: boolean;
  }>();

  // Build resource list based on scope type
  const resources = $derived.by(() => {
    switch (scopeType) {
      case "space":
        return spaces.map((s) => ({ id: s.id, name: s.name, type: "space" as const }));
      case "assistant":
        return assistants.map((a) => ({
          id: a.id,
          name: a.name,
          type: "assistant" as const
        }));
      case "app":
        return apps.map((a) => ({
          id: a.id,
          name: a.name,
          type: "app" as const,
          spaceName: a.spaceName
        }));
      default:
        return [];
    }
  });

  // Find selected resource
  const selectedResource = $derived(resources.find((r) => r.id === value));

  const {
    elements: { menu, input, option, label },
    states: { open, inputValue, touchedInput },
    helpers: { isSelected }
  } = createCombobox<Resource>({
    forceVisible: true,
    portal: null
  });

  // Filter resources based on search input
  const filteredResources = $derived.by(() => {
    if (!$touchedInput || !$inputValue) {
      return resources;
    }
    const query = $inputValue.toLowerCase();
    return resources.filter(
      (r) =>
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
  <span use:melt={$label} class="mb-1.5 block text-sm font-medium text-default">
    {m.api_keys_select_resource({ scopeType })}
  </span>

  <div class="relative">
    <!-- Search Icon -->
    <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted pointer-events-none" />

    <!-- Input -->
    <input
      use:melt={$input}
      class="h-11 w-full rounded-lg border border-default bg-primary pl-10 pr-16 text-sm
             placeholder:text-muted transition-all duration-150
             hover:border-dimmer focus:border-accent-default focus:ring-2 focus:ring-accent-default/20
             disabled:cursor-not-allowed disabled:opacity-50"
      placeholder={m.api_keys_search_resource({ scopeType })}
      {disabled}
    />

    <!-- Right side icons -->
    <div class="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
      {#if value}
        <button
          type="button"
          onclick={clearSelection}
          class="rounded p-1 text-muted hover:bg-hover-default hover:text-default transition-colors"
          aria-label="Clear selection"
        >
          <X class="h-4 w-4" />
        </button>
      {/if}
      <ChevronDown
        class="h-4 w-4 text-muted transition-transform duration-200 {$open ? 'rotate-180' : ''}"
      />
    </div>
  </div>

  <!-- Selected resource badge -->
  {#if selectedResource}
    <div class="mt-2 flex items-center gap-2">
      <div
        class="inline-flex items-center gap-2 rounded-lg border border-accent-default/30 bg-accent-default/5 px-3 py-1.5"
      >
        <Icon class="h-4 w-4 text-accent-default" />
        <span class="text-sm font-medium text-default">{selectedResource.name}</span>
        {#if selectedResource.spaceName}
          <span class="text-xs text-muted">· {selectedResource.spaceName}</span>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Dropdown menu -->
  {#if $open}
    <div
      use:melt={$menu}
      class="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-default bg-primary shadow-lg"
      transition:fly={{ y: -4, duration: 150 }}
    >
      {#if filteredResources.length === 0}
        <div class="px-4 py-8 text-center">
          <div class="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-secondary">
            <Search class="h-5 w-5 text-muted" />
          </div>
          <p class="text-sm text-muted">{m.api_keys_no_resource_found({ scopeType })}</p>
          {#if $inputValue}
            <p class="mt-1 text-xs text-muted">{m.api_keys_try_different_search()}</p>
          {/if}
        </div>
      {:else}
        <div class="p-1">
          {#each filteredResources as resource (resource.id)}
            {@const selected = $isSelected(resource)}
            <button
              use:melt={$option({ value: resource, label: resource.name })}
              type="button"
              class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors
                     hover:bg-hover-default
                     data-[highlighted]:bg-hover-default
                     {selected ? 'bg-accent-default/5' : ''}"
              onclick={() => handleSelect(resource)}
            >
              <!-- Resource type icon -->
              <div
                class="flex h-8 w-8 items-center justify-center rounded-lg
                       {selected ? 'bg-accent-default/15 text-accent-default' : 'bg-secondary text-muted'}"
              >
                <Icon class="h-4 w-4" />
              </div>

              <!-- Resource info -->
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-default truncate">{resource.name}</p>
                {#if resource.spaceName}
                  <p class="text-xs text-muted truncate">{m.api_keys_in_space({ spaceName: resource.spaceName })}</p>
                {:else}
                  <p class="text-xs text-muted font-mono truncate">{resource.id.slice(0, 8)}...</p>
                {/if}
              </div>

              <!-- Selected check -->
              {#if selected}
                <Check class="h-4 w-4 text-accent-default flex-shrink-0" />
              {/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
