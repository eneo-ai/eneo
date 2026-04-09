<script lang="ts">
  import type { SpaceSparse } from "@intric/intric-js";
  import { Check, ChevronDown, Building2, MessageSquare, AppWindow, X } from "lucide-svelte";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { selectTriggerClass } from "$lib/components/ui/select/index.js";

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
    disabled = false,
    id = "scope-resource-trigger",
    label,
    placeholder
  } = $props<{
    /** When `null`, the picker renders disabled with the placeholder text. */
    scopeType: ResourceType | null;
    value?: string | null;
    spaces?: SpaceSparse[];
    assistants?: ResourceOption[];
    apps?: ResourceOption[];
    disabled?: boolean;
    /** Trigger element id, used for label association. Override if rendering more than one. */
    id?: string;
    /** Override the field label. Defaults to `m.api_keys_select_resource({ scopeType })`. */
    label?: string;
    /** Override the trigger placeholder when nothing is selected. Defaults to the same. */
    placeholder?: string;
  }>();

  let open = $state(false);
  let triggerRef = $state<HTMLButtonElement | null>(null);

  // Build resource list based on scope type. When `scopeType` is null the list is empty
  // (and the trigger is rendered disabled — see `isDisabled` below).
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

  function getIcon(type: ResourceType | null) {
    switch (type) {
      case "assistant":
        return MessageSquare;
      case "app":
        return AppWindow;
      // `space` and the null/disabled state both fall back to the building icon.
      case "space":
      default:
        return Building2;
    }
  }

  // Reset the bound value whenever the scope type changes (including when it becomes null) so a
  // stale id from a previous type can never leak through to the parent's filter params.
  $effect(() => {
    void scopeType;
    value = null;
  });

  const isDisabled = $derived(disabled || scopeType === null);
  const Icon = $derived(getIcon(scopeType));

  // Default-on-the-fly translation lookups: only run when scopeType is non-null. The disabled
  // state uses the explicit `placeholder` prop if provided, otherwise falls back to the new
  // admin-flavored "choose a scope type first" message.
  const defaultLabel = $derived(
    scopeType === null
      ? m.api_keys_admin_label_scope_target()
      : m.api_keys_select_resource({ scopeType })
  );
  const defaultPlaceholder = $derived(
    scopeType === null
      ? m.api_keys_admin_scope_target_placeholder()
      : m.api_keys_select_resource({ scopeType })
  );
  const fieldLabel = $derived(label ?? defaultLabel);
  const triggerPlaceholder = $derived(placeholder ?? defaultPlaceholder);
  const triggerText = $derived(selectedResource?.name ?? triggerPlaceholder);
  const searchPlaceholder = $derived(
    scopeType === null ? triggerPlaceholder : m.api_keys_search_resource({ scopeType })
  );
  const emptyText = $derived(
    scopeType === null ? triggerPlaceholder : m.api_keys_no_resource_found({ scopeType })
  );
</script>

<Field.Field>
  <Field.Label for={id}>{fieldLabel}</Field.Label>

  <Popover.Root bind:open>
    <Popover.Trigger>
      {#snippet child({ props })}
        <button
          {...props}
          {id}
          bind:this={triggerRef}
          type="button"
          role="combobox"
          aria-expanded={open}
          disabled={isDisabled}
          data-slot="select-trigger"
          data-size="default"
          data-placeholder={selectedResource ? undefined : ""}
          class={selectTriggerClass}
        >
          <span class="flex min-w-0 items-center gap-1.5">
            <Icon class="text-muted-foreground size-4 shrink-0" />
            <span class="truncate">{triggerText}</span>
          </span>
          <span class="flex shrink-0 items-center gap-1">
            {#if value && !isDisabled}
              <span
                role="button"
                tabindex="0"
                aria-label="Clear selection"
                class="hover:bg-muted text-muted-foreground hover:text-foreground rounded p-0.5 transition-colors"
                onclick={clearSelection}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    value = null;
                  }
                }}
              >
                <X class="size-3" />
              </span>
            {/if}
            <ChevronDown class="text-muted-foreground size-4" />
          </span>
        </button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content class="w-(--bits-popover-anchor-width) min-w-[280px] p-0" align="start">
      <Command.Root>
        <Command.Input placeholder={searchPlaceholder} />
        <Command.List>
          <Command.Empty>{emptyText}</Command.Empty>
          <Command.Group>
            {#each resources as resource (resource.id)}
              {@const selected = resource.id === value}
              <Command.Item
                value={`${resource.name} ${resource.id} ${resource.spaceName ?? ""}`}
                onSelect={() => handleSelect(resource)}
              >
                <Icon class="text-muted-foreground size-4 shrink-0" />
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
                  <Check class="text-accent-default size-4 shrink-0" />
                {/if}
              </Command.Item>
            {/each}
          </Command.Group>
        </Command.List>
      </Command.Root>
    </Popover.Content>
  </Popover.Root>
</Field.Field>
