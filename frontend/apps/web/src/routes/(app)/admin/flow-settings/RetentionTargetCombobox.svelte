<script lang="ts">
  import Check from "lucide-svelte/icons/check";
  import ChevronsUpDown from "lucide-svelte/icons/chevrons-up-down";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Target = { id: string; name: string };

  let {
    id,
    label,
    placeholder,
    items,
    loadMoreLabel,
    value = null,
    disabled = false,
    loading = false,
    hasMore = false,
    onSelect,
    onLoadMore
  }: {
    id: string;
    label: string;
    placeholder: string;
    items: readonly Target[];
    loadMoreLabel: string;
    value?: string | null;
    disabled?: boolean;
    loading?: boolean;
    hasMore?: boolean;
    onSelect: (id: string) => void;
    onLoadMore: () => void;
  } = $props();

  let open = $state(false);
  let filter = $state("");

  const selectedName = $derived(items.find((i) => i.id === value)?.name ?? null);

  // The endpoint pages by offset and takes no search term, so filtering can
  // only cover what has been fetched. Say so rather than let an admin conclude
  // a space does not exist.
  const shown = $derived.by(() => {
    const q = filter.trim().toLocaleLowerCase();
    if (!q) return items;
    return items.filter((i) => i.name.toLocaleLowerCase().includes(q));
  });
</script>

<Popover.Root bind:open>
  <Popover.Trigger {id} {disabled} aria-label={label}>
    {#snippet child({ props })}
      <Button
        {...props}
        variant="outline"
        role="combobox"
        aria-expanded={open}
        class="focus-visible:outline-accent-default w-full justify-between font-normal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solid"
      >
        <span class="truncate" class:text-muted={!selectedName}>
          {selectedName ?? placeholder}
        </span>
        <ChevronsUpDown class="text-muted size-4 shrink-0" aria-hidden="true" />
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-(--bits-popover-anchor-width) p-0" align="start">
    <Command.Root shouldFilter={false}>
      <Command.Input bind:value={filter} placeholder={m.flow_run_retention_target_search()} />
      <Command.List>
        <Command.Empty>{m.flow_run_retention_target_no_match()}</Command.Empty>
        {#each shown as item (item.id)}
          <Command.Item
            value={item.id}
            onSelect={() => {
              onSelect(item.id);
              open = false;
            }}
          >
            <Check
              class="size-4 shrink-0 {item.id === value ? '' : 'opacity-0'}"
              aria-hidden="true"
            />
            <span class="truncate">{item.name}</span>
          </Command.Item>
        {/each}
        {#if hasMore}
          <Command.Separator />
          <div class="text-muted px-2 py-1.5 text-xs">
            {m.flow_run_retention_target_partial({ count: items.length })}
          </div>
          <Command.Item
            value="__load-more__"
            disabled={loading}
            onSelect={() => onLoadMore()}
            class="text-accent-stronger justify-center font-medium"
          >
            {loadMoreLabel}
          </Command.Item>
        {/if}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
