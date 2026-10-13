<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import type { VariablePickerContext } from "$lib/features/flows/components/VariablePicker.svelte";
  import { toolRefusalSentence } from "$lib/features/flows/flowToolRefusal";
  import type { JsonObject } from "$lib/features/flows/jsonObject";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import ToolArgumentRow from "./ToolArgumentRow.svelte";
  import ToolArgumentsJson from "./ToolArgumentsJson.svelte";
  import ToolOtherArguments from "./ToolOtherArguments.svelte";
  import ToolPicker from "./ToolPicker.svelte";
  import {
    findToolOption,
    readArgument,
    withArgument,
    type FlowToolOption,
    type StoredToolInputConfig,
    type ToolInputConfig,
    type ToolOptionsLoad
  } from "./toolInputConfig";
  import { readToolArgumentForm } from "./toolInputSchema";

  let {
    config,
    toolOptions,
    stepKey,
    isPublished,
    variableContext,
    onConfigChange,
    onReloadOptions
  }: {
    /** The step's stored tool choice; null while no tool is chosen. */
    config: StoredToolInputConfig | null;
    /** The flow's tools as the editor holds them; it loads them once for all steps. */
    toolOptions: ToolOptionsLoad;
    /** Identifies the step being edited, so one step's unfinished values never show on another. */
    stepKey: string;
    isPublished: boolean;
    variableContext?: VariablePickerContext;
    onConfigChange?: (detail: { config: ToolInputConfig }) => void;
    onReloadOptions?: () => void;
  } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  // The permission the space menu asks for its Settings entry.
  const mayEditSpace = $derived(
    !$currentSpace.personal && $currentSpace.hasPermission("edit", "space")
  );

  const options = $derived(toolOptions.status === "loaded" ? toolOptions.options : []);
  const refreshing = $derived(toolOptions.status === "loaded" && toolOptions.refreshing);
  const selected = $derived(findToolOption(options, config));
  const storedArguments = $derived(Object.entries(config?.arguments ?? {}));
  const form = $derived(readToolArgumentForm(selected?.input_schema));
  const namedArguments = $derived(
    form.kind === "fields" ? form.fields.map(({ name }) => name) : []
  );
  // Stored arguments the tool's schema does not name; none when the schema is
  // not shown as rows, where every stored argument is in the JSON field. An
  // open schema takes them; a closed one no longer has them.
  const unnamedArguments = $derived(
    form.kind === "json" ? [] : storedArguments.filter(([name]) => !namedArguments.includes(name))
  );

  function write(mcpServerId: string, toolId: string, toolArguments: JsonObject) {
    onConfigChange?.({
      config: { mcp_server_id: mcpServerId, tool_id: toolId, arguments: toolArguments }
    });
  }

  function chooseTool(option: FlowToolOption) {
    if (option !== selected) {
      // The arguments belong to the tool, so another tool starts without any.
      write(option.mcp_server_id, option.tool_id, {});
    } else if (config?.hasOtherKeys) {
      // The server refuses a choice with keys of its own; choosing the tool
      // again stores the choice the way the editor writes it.
      write(config.mcp_server_id, config.tool_id, config.arguments);
    }
  }

  function setArguments(next: JsonObject) {
    if (config) write(config.mcp_server_id, config.tool_id, next);
  }

  /** The named arguments as stored, beside `others` in place of the unnamed ones. */
  function setOtherArguments(others: JsonObject) {
    setArguments(
      Object.fromEntries([
        ...storedArguments.filter(([name]) => namedArguments.includes(name)),
        ...Object.entries(others)
      ])
    );
  }

  const warningAlertClass = "border-warning-default/30 bg-warning-dimmer rounded-[9px]";
  const warningTextClass = "text-warning-stronger text-xs leading-relaxed";
</script>

{#snippet refreshButton()}
  <Button
    variant="outline"
    size="sm"
    disabled={refreshing}
    aria-busy={refreshing}
    onclick={() => onReloadOptions?.()}
  >
    {#if refreshing}
      <Spinner data-icon="inline-start" aria-hidden="true" />
    {:else}
      <RefreshCw data-icon="inline-start" aria-hidden="true" />
    {/if}
    {m.flow_tool_options_refresh()}
  </Button>
{/snippet}

{#snippet storedArgumentList(entries: [string, unknown][])}
  <ul class="flex flex-col gap-1.5">
    {#each entries as [name, value] (name)}
      <li class="flex items-start justify-between gap-2">
        <span class="min-w-0 font-mono text-xs break-all" translate="no"
          >{name}: {JSON.stringify(value)}</span
        >
        {#if !isPublished && config && selected}
          <Button
            variant="outline"
            size="sm"
            aria-label={m.flow_tool_argument_remove({ argument: name })}
            onclick={() => setArguments(withArgument(config.arguments, name, undefined))}
          >
            {m.remove()}
          </Button>
        {/if}
      </li>
    {/each}
  </ul>
{/snippet}

<FlowStepSection title={m.flow_tool_config_title()}>
  <Settings.Row
    title={m.flow_tool_picker_title()}
    description={m.flow_tool_picker_desc()}
    density="compact"
  >
    <div class="flex flex-col gap-2">
      {#if toolOptions.status === "loading"}
        <div class="flex flex-col gap-2" role="status" aria-label={m.flow_tool_options_loading()}>
          <Skeleton class="h-8 w-full" />
          <Skeleton class="h-4 w-2/3" />
        </div>
      {:else if toolOptions.status === "failed"}
        <Alert.Root variant="destructive">
          <Alert.Description>{toolOptions.message}</Alert.Description>
        </Alert.Root>
        <Button variant="outline" size="sm" class="w-fit" onclick={() => onReloadOptions?.()}>
          {m.retry()}
        </Button>
      {:else}
        {#if config && !selected}
          <Alert.Root class={warningAlertClass}>
            <Alert.Description class={warningTextClass}>
              {m.flow_tool_stored_missing()}
              {#if !isPublished}
                {m.flow_tool_stored_missing_action()}
              {/if}
            </Alert.Description>
          </Alert.Root>
        {/if}
        {#if options.length === 0}
          <Empty.Root>
            <Empty.Header>
              <Empty.Title>{m.flow_tool_options_empty()}</Empty.Title>
              <Empty.Description>
                {#if $currentSpace.personal}
                  {toolRefusalSentence("space_is_personal")}
                {:else if mayEditSpace}
                  {m.flow_tool_options_empty_editor()}
                {:else}
                  {m.flow_tool_options_empty_admin()}
                {/if}
              </Empty.Description>
            </Empty.Header>
            <Empty.Content>
              {#if mayEditSpace}
                <Button
                  variant="outline"
                  size="sm"
                  href={localizeHref(`/spaces/${$currentSpace.routeId}/settings`)}
                >
                  {m.flow_tool_options_open_settings()}
                </Button>
              {/if}
              {@render refreshButton()}
            </Empty.Content>
          </Empty.Root>
        {:else}
          <div class="flex flex-wrap items-center gap-2">
            <div class="min-w-0 flex-1">
              <ToolPicker {options} {selected} disabled={isPublished} onSelect={chooseTool} />
            </div>
            {#if !isPublished}
              {@render refreshButton()}
            {/if}
          </div>
          <p class="text-muted text-xs leading-relaxed">{m.flow_tool_picker_help()}</p>
        {/if}
        {#if selected?.refusal}
          <Alert.Root class={warningAlertClass}>
            <Alert.Description class={warningTextClass}>
              {toolRefusalSentence(selected.refusal)}
            </Alert.Description>
          </Alert.Root>
        {/if}
      {/if}
    </div>
  </Settings.Row>

  {#if selected && config}
    <Settings.Row
      title={m.flow_tool_arguments_title()}
      description={m.flow_tool_arguments_desc()}
      fullWidth={true}
      density="compact"
    >
      <div class="flex flex-col gap-3">
        {#if form.kind === "none"}
          <p class="text-secondary text-sm">{m.flow_tool_no_arguments()}</p>
        {:else if form.kind === "json"}
          {#key `${stepKey}:${config.tool_id}`}
            <ToolArgumentsJson
              value={config.arguments}
              disabled={isPublished}
              onChange={setArguments}
            />
          {/key}
        {:else}
          {#each form.fields as field (`${stepKey}:${config.tool_id}:${field.name}`)}
            <ToolArgumentRow
              {field}
              value={readArgument(config.arguments, field.name)}
              disabled={isPublished}
              {variableContext}
              onChange={(value) => setArguments(withArgument(config.arguments, field.name, value))}
            />
          {/each}
        {/if}
        {#if form.kind === "fields" && !form.closed}
          {#key `${stepKey}:${config.tool_id}`}
            <ToolOtherArguments
              value={Object.fromEntries(unnamedArguments)}
              {namedArguments}
              disabled={isPublished}
              onChange={setOtherArguments}
            />
          {/key}
        {:else if unnamedArguments.length > 0}
          <div class="flex flex-col gap-2">
            <h4 class="text-sm font-medium">{m.flow_tool_arguments_removed_title()}</h4>
            {@render storedArgumentList(unnamedArguments)}
          </div>
        {/if}
      </div>
    </Settings.Row>
  {:else if toolOptions.status !== "loading" && config && storedArguments.length > 0}
    <Settings.Row title={m.flow_tool_stored_arguments_title()} fullWidth={true} density="compact">
      {@render storedArgumentList(storedArguments)}
    </Settings.Row>
  {/if}
</FlowStepSection>
