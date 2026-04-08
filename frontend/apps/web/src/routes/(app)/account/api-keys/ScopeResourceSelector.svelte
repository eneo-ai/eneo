<script lang="ts">
  import type { SpaceSparse } from "@intric/intric-js";
  import { Check, ChevronsUpDown, Building2, MessageSquare, AppWindow, X } from "lucide-svelte";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

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

  let open = $state(false);
  let triggerRef = $state<HTMLButtonElement | null>(null);

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

  const selectedResource = $derived(resources.find((r: Resource) => r.id === value));

  function handleSelect(resource: Resource) {
    value = resource.id;
    open = false;
    void tick().then(() => triggerRef?.focus());
  }

  function clearSelection(event: MouseEvent) {
    event.stopPropagation();
    value = null;
  }

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

  // Reset when scope type changes
  $effect(() => {
    if (scopeType) {
      value = null;
    }
  });

  const Icon = $derived(getIcon(scopeType));
  const triggerLabel = $derived(
    selectedResource?.name ?? m.api_keys_search_resource({ scopeType })
  );
</script>

<div class="w-full">
  <span id="scope-resource-label" class="text-default mb-1.5 block text-sm font-medium">
    {m.api_keys_select_resource({ scopeType })}
  </span>

  <Popover.Root bind:open>
    <Popover.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          bind:ref={triggerRef}
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-labelledby="scope-resource-label"
          {disabled}
          class="h-11 w-full justify-between"
        >
          <span class="flex min-w-0 items-center gap-2">
            <Icon class="text-muted h-4 w-4 shrink-0" />
            <span class="truncate {selectedResource ? 'text-default' : 'text-muted'}">
              {triggerLabel}
            </span>
          </span>
          <span class="flex shrink-0 items-center gap-1">
            {#if value}
              <span
                role="button"
                tabindex="0"
                aria-label="Clear selection"
                class="hover:bg-hover-default text-muted hover:text-default rounded p-1 transition-colors"
                onclick={clearSelection}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    value = null;
                  }
                }}
              >
                <X class="h-3.5 w-3.5" />
              </span>
            {/if}
            <ChevronsUpDown class="text-muted h-4 w-4 opacity-60" />
          </span>
        </Button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content class="w-(--bits-popover-anchor-width) min-w-[280px] p-0" align="start">
      <Command.Root>
        <Command.Input placeholder={m.api_keys_search_resource({ scopeType })} />
        <Command.List>
          <Command.Empty>{m.api_keys_no_resource_found({ scopeType })}</Command.Empty>
          <Command.Group>
            {#each resources as resource (resource.id)}
              {@const selected = resource.id === value}
              <Command.Item
                value={`${resource.name} ${resource.id} ${resource.spaceName ?? ""}`}
                onSelect={() => handleSelect(resource)}
              >
                <Icon class="text-muted h-4 w-4 shrink-0" />
                <div class="min-w-0 flex-1">
                  <p class="text-default truncate text-sm font-medium">{resource.name}</p>
                  {#if resource.spaceName}
                    <p class="text-muted truncate text-xs">
                      {m.api_keys_in_space({ spaceName: resource.spaceName })}
                    </p>
                  {:else}
                    <p class="text-muted truncate font-mono text-xs">
                      {resource.id.slice(0, 8)}...
                    </p>
                  {/if}
                </div>
                {#if selected}
                  <Check class="text-accent-default h-4 w-4 shrink-0" />
                {/if}
              </Command.Item>
            {/each}
          </Command.Group>
        </Command.List>
      </Command.Root>
    </Popover.Content>
  </Popover.Root>
</div>
