<script lang="ts">
  import { computeCommandScore } from "bits-ui";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { selectTriggerClass } from "$lib/components/ui/select/index.js";
  import { toolRefusalSentence } from "$lib/features/flows/flowToolRefusal";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import type { FlowToolOption } from "./toolInputConfig";

  let {
    options,
    selected,
    disabled,
    onSelect
  }: {
    options: FlowToolOption[];
    selected: FlowToolOption | null;
    disabled: boolean;
    onSelect: (option: FlowToolOption) => void;
  } = $props();

  const uid = $props.id();
  let open = $state(false);

  type ServerGroup = { serverId: string; serverName: string; options: FlowToolOption[] };

  const groups = $derived.by(() => {
    const result: ServerGroup[] = [];
    for (const option of options) {
      const group = result.find((candidate) => candidate.serverId === option.mcp_server_id);
      if (group) group.options.push(option);
      else {
        result.push({
          serverId: option.mcp_server_id,
          serverName: option.mcp_server_name,
          options: [option]
        });
      }
    }
    return result;
  });

  // A refused tool stays an ordinary item, so the arrow keys reach it and its
  // reason is read out; choosing it does nothing.
  function choose(option: FlowToolOption) {
    if (option.refusal !== null) return;
    open = false;
    onSelect(option);
  }
</script>

<span id="{uid}-label" class="sr-only">{m.flow_tool_picker_title()}</span>
<Popover.Root bind:open>
  <Popover.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-labelledby="{uid}-label {uid}-value"
        {disabled}
        data-slot="select-trigger"
        data-size="default"
        data-placeholder={selected ? undefined : ""}
        class={cn(selectTriggerClass, "h-auto min-h-8 w-full whitespace-normal")}
      >
        <span
          id="{uid}-value"
          class="min-w-0 text-left break-all"
          translate={selected ? "no" : undefined}
        >
          {selected?.tool_name ?? m.flow_tool_picker_placeholder()}
        </span>
        <ChevronDown class="text-muted-foreground size-4" aria-hidden="true" />
      </button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-(--bits-popover-anchor-width) min-w-[280px] p-0" align="start">
    <!-- An item's value is its ids, which keeps it unique; the search reads the
         names and the approved description. -->
    <Command.Root
      label={m.flow_tool_picker_search()}
      filter={(_value, search, keywords) => computeCommandScore(keywords?.join(" ") ?? "", search)}
    >
      <Command.Input placeholder={m.flow_tool_picker_search()} />
      <Command.List class="max-h-[min(24rem,60vh)]">
        <Command.Empty>{m.flow_tool_picker_no_match()}</Command.Empty>
        {#each groups as group (group.serverId)}
          <Command.Group heading={group.serverName} value={group.serverId}>
            {#each group.options as option (option.tool_id)}
              <Command.Item
                value={`${option.mcp_server_id}:${option.tool_id}`}
                keywords={[option.tool_name, group.serverName, option.tool_description ?? ""]}
                data-checked={option === selected}
                aria-describedby={option.refusal ? `${uid}-${option.tool_id}-refusal` : undefined}
                onSelect={() => choose(option)}
                class="items-start gap-2.5 py-2"
              >
                <span class="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span
                    translate="no"
                    class="text-sm font-medium break-all {option.refusal
                      ? 'text-muted'
                      : 'text-primary'}">{option.tool_name}</span
                  >
                  {#if option.tool_description}
                    <span class="text-secondary line-clamp-2 text-xs leading-relaxed"
                      >{option.tool_description}</span
                    >
                  {/if}
                  {#if option.refusal}
                    <span
                      id="{uid}-{option.tool_id}-refusal"
                      class="text-warning-stronger text-xs leading-relaxed"
                      >{toolRefusalSentence(option.refusal)}</span
                    >
                  {/if}
                </span>
              </Command.Item>
            {/each}
          </Command.Group>
        {/each}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
