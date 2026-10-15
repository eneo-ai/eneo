<script lang="ts">
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Plug from "@lucide/svelte/icons/plug";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import type { VariablePickerContext } from "$lib/features/flows/components/VariablePicker.svelte";
  import {
    securityClassName,
    type NamedSecurityLevel
  } from "$lib/features/flows/flowClassificationNames";
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
    draftPlace,
    findToolOption,
    keptDraftText,
    listedToolOptions,
    readArgument,
    typedDraft,
    withArgument,
    type ArgumentsScope,
    type FlowToolOption,
    type ToolArgumentsDraft,
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
    classifications = [],
    argumentsDrafts = new Map(),
    onConfigChange,
    onArgumentsDraftChange,
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
    /** The organization's security classes, which name the level of the chosen tool's server. */
    classifications?: readonly NamedSecurityLevel[];
    /** The arguments texts the editor keeps for this step, by field, because the step cannot hold them. */
    argumentsDrafts?: ReadonlyMap<string, ToolArgumentsDraft>;
    onConfigChange?: (detail: { config: ToolInputConfig }) => void;
    /** Called with a field's arguments text the step cannot hold, or null once it is stored. */
    onArgumentsDraftChange?: (place: string, draft: ToolArgumentsDraft | null) => void;
    onReloadOptions?: () => void;
  } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  // The permission the space menu asks for its Settings entry.
  const mayEditSpace = $derived(
    !$currentSpace.personal && $currentSpace.hasPermission("edit", "space")
  );

  const options = $derived(listedToolOptions(toolOptions));
  const refreshing = $derived(toolOptions.status === "loaded" && toolOptions.refreshing);
  const selected = $derived(findToolOption(options, config));
  const classificationsEnabled = $derived(
    toolOptions.status === "loaded" && toolOptions.classificationsEnabled
  );
  const serverLevel = $derived(selected?.mcp_server_security_level ?? null);
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
  // The JSON field writes every argument without a row of its own.
  const jsonScope = $derived<ArgumentsScope>({ except: namedArguments });

  /** The text kept for the field with `scope` while the step holds what it was typed against. */
  function keptText(scope: ArgumentsScope): string | null {
    return keptDraftText(argumentsDrafts.get(draftPlace(scope)), config);
  }

  function keepUnsavedText(scope: ArgumentsScope, text: string | null) {
    if (!config) return;
    onArgumentsDraftChange?.(
      draftPlace(scope),
      text === null ? null : typedDraft(text, scope, config)
    );
  }

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

<!-- Rows of the step's Underlag section, right under its source: the tool is
     the choice that source asks for. -->
<Settings.Row
  title={m.flow_tool_picker_title()}
  description={m.flow_tool_picker_desc()}
  density="compact"
>
  <div class="flex flex-col gap-2" data-step-focus="tool">
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
        <Empty.Root class="border">
          <Empty.Header>
            <Empty.Media variant="icon"><Plug aria-hidden="true" /></Empty.Media>
            <Empty.Title>{m.flow_tool_options_empty()}</Empty.Title>
            <Empty.Description>
              {$currentSpace.personal
                ? toolRefusalSentence("space_is_personal")
                : m.flow_tool_options_empty_lead()}
            </Empty.Description>
          </Empty.Header>
          <Empty.Content>
            {#if !$currentSpace.personal}
              <ol
                class="text-muted-foreground flex list-decimal flex-col gap-1.5 self-stretch pl-5 text-left text-sm/relaxed"
              >
                <li>{m.flow_tool_options_empty_step_server()}</li>
                <li>
                  {mayEditSpace
                    ? m.flow_tool_options_empty_editor()
                    : m.flow_tool_options_empty_admin()}
                </li>
                <li>{m.flow_tool_options_empty_step_listed()}</li>
              </ol>
            {/if}
            {#if mayEditSpace}
              <!-- A new tab: leaving the editor saves the flow first, which a
                   tool step without a tool cannot be. -->
              <Button
                variant="outline"
                size="sm"
                href={localizeHref(`/spaces/${$currentSpace.routeId}/settings`)}
                target="_blank"
                rel="noopener noreferrer"
              >
                {m.flow_tool_options_open_settings()}
                <ExternalLink data-icon="inline-end" aria-hidden="true" />
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
        {#if selected}
          <div class="flex flex-col gap-0.5">
            <p class="text-secondary text-xs font-medium">
              {m.flow_tool_picker_server({ name: selected.mcp_server_name })}
            </p>
            {#if selected.tool_description}
              <p class="text-muted line-clamp-3 text-xs leading-relaxed">
                {selected.tool_description}
              </p>
            {/if}
          </div>
        {/if}
        <p class="text-muted text-xs leading-relaxed">{m.flow_tool_picker_help()}</p>
      {/if}
      {#if selected?.refusal}
        <Alert.Root class={warningAlertClass}>
          <Alert.Description class={warningTextClass}>
            {toolRefusalSentence(selected.refusal)}
          </Alert.Description>
        </Alert.Root>
      {/if}
      {#if selected && classificationsEnabled}
        {#if serverLevel !== null}
          <div class="flex flex-col gap-1">
            <p class="text-secondary text-xs font-medium">
              {m.flow_tool_server_class({
                name: securityClassName(classifications, serverLevel)
              })}
            </p>
            <p class="text-muted text-xs leading-relaxed">{m.flow_tool_server_class_rule()}</p>
          </div>
        {:else}
          <p class="text-muted text-xs leading-relaxed">{m.flow_tool_server_no_class()}</p>
        {/if}
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
    <div class="flex flex-col gap-3" data-step-focus="tool_arguments">
      {#if form.kind === "none"}
        <p class="text-secondary text-sm">{m.flow_tool_no_arguments()}</p>
      {:else if form.kind === "json"}
        <!-- The editor cannot split this schema into rows (a reference, a
             combination), so the author reads it as approved. -->
        {#if selected.input_schema}
          <Collapsible.Root class="flex flex-col gap-2">
            <Collapsible.Trigger
              class="group focus-visible:ring-ring flex min-h-8 w-fit items-center gap-1.5 rounded-sm text-sm font-medium outline-none focus-visible:ring-2"
            >
              <ChevronRight
                class="text-secondary size-3.5 shrink-0 group-data-[state=open]:rotate-90 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
                aria-hidden="true"
              />
              {m.flow_tool_arguments_schema_show()}
            </Collapsible.Trigger>
            <Collapsible.Content>
              <pre
                class="bg-secondary text-primary max-h-72 overflow-auto rounded-md px-3 py-2 font-mono text-xs"
                translate="no">{JSON.stringify(selected.input_schema, null, 2)}</pre>
            </Collapsible.Content>
          </Collapsible.Root>
        {/if}
        {#key `${stepKey}:${config.tool_id}`}
          <ToolArgumentsJson
            value={config.arguments}
            disabled={isPublished}
            onChange={setArguments}
            keptText={keptText(jsonScope)}
            onUnsavedText={(text) => keepUnsavedText(jsonScope, text)}
            {variableContext}
          />
        {/key}
      {:else}
        {#each form.fields as field (`${stepKey}:${config.tool_id}:${field.name}`)}
          <ToolArgumentRow
            {field}
            value={readArgument(config.arguments, field.name)}
            disabled={isPublished}
            {variableContext}
            keptText={keptText({ only: field.name })}
            onUnsavedText={(text) => keepUnsavedText({ only: field.name }, text)}
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
            keptText={keptText(jsonScope)}
            onUnsavedText={(text) => keepUnsavedText(jsonScope, text)}
            {variableContext}
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
