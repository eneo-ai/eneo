<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { invalidate } from "$app/navigation";
  import { writable } from "svelte/store";
  import { untrack } from "svelte";
  import {
    Calculator,
    ChartColumn,
    ChevronDown,
    Package,
    Plus,
    Server,
    ShieldCheck,
    Wrench,
    CircleCheck,
    CircleDashed,
    TriangleAlert,
    Power,
    Pause,
    Pencil,
    Trash2,
    ChevronRight
  } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import { CAPABILITIES } from "$lib/features/mcp/capabilities";
  import { readinessMessage } from "$lib/features/mcp/readiness";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { setSecurityContext } from "$lib/features/security-classifications/SecurityContext";
  import type { components } from "@eneo/eneo-js";
  import type { PageData } from "./$types";
  import MCPServersTable from "../mcp-servers/MCPServersTable.svelte";
  import MCPServerDialog from "../mcp-servers/MCPServerDialog.svelte";
  import DeleteMCPDialog from "../mcp-servers/DeleteMCPDialog.svelte";
  import MCPToolsPanel from "../mcp-servers/MCPToolsPanel.svelte";
  import ProviderToolsSummary from "./ProviderToolsSummary.svelte";

  type Provider = components["schemas"]["MCPServerSettingsPublic"];
  let { data }: { data: PageData } = $props();
  const uid = $props.id();
  setSecurityContext(untrack(() => data.securityClassifications));
  const open = writable(false);
  const tabController = writable("functions");
  let deleteOpen = $state(false);
  let deleting = $state<Provider | null>(null);
  let purpose = $state("general");
  let editing = $state<Provider | null>(null);
  let busy = $state<string | null>(null);
  let error = $state("");
  let notice = $state("");
  // The capability card a notice or error belongs to; null shows it at the top of the tab.
  let messagePurpose = $state<string | null>(null);
  let reviewing = $state<string | null>(null);
  const servers = $derived(data.mcpSettings.items ?? []);
  // Servers built into Eneo (the bundled tool runtime) that this tenant has not added yet:
  // general ones on the MCP servers tab, capability providers on their capability card. A
  // capability card also shows a provider the deployment has not enabled, so admins learn it
  // exists; a general server that is not enabled is simply not offered.
  const bundledToAdd = $derived((data.bundled.items ?? []).filter((tool) => !tool.mcp_server_id));
  const bundledServersToAdd = $derived(
    bundledToAdd.filter((tool) => tool.available && tool.purpose === "general")
  );
  const bundledProviderFor = (purpose: string) =>
    bundledToAdd.find((tool) => tool.purpose === purpose);
  // Names and blurbs of the general bundled servers; capability providers are named by
  // their capability instead.
  const BUNDLED_SERVERS: Record<
    string,
    { label: () => string; description: () => string; icon: typeof Calculator }
  > = {
    compute: {
      label: m.tools_bundled_compute,
      description: m.tools_bundled_compute_description,
      icon: Calculator
    },
    charts: {
      label: m.tools_bundled_charts,
      description: m.tools_bundled_charts_description,
      icon: ChartColumn
    }
  };
  const bundledServerLabel = (tool: string) => BUNDLED_SERVERS[tool]?.label() ?? tool;
  const DEPLOYMENT_GUIDE_URL =
    "https://docs.eneo.ai/docs/builtin-tool-servers#bundled-isolated-providers";
  let addingBundled = $state(false);
  let showFunctionServers = $state(false);
  const external = $derived(
    servers.filter(
      (s) =>
        s.http_auth_type !== "internal" &&
        (showFunctionServers || (s.purpose ?? "general") === "general")
    )
  );

  function configure(selectedPurpose: string, provider: Provider | null = null) {
    purpose = selectedPurpose;
    editing = provider;
    error = "";
    messagePurpose = null;
    open.set(true);
  }

  async function refresh() {
    await Promise.all([
      invalidate("admin:tools"),
      invalidate("admin:layout"),
      invalidate("spaces:data")
    ]);
  }

  async function save(payload: Record<string, unknown>, id?: string) {
    if (id) await data.eneo.mcpServers.update({ id, ...payload });
    else {
      // The dialog builds the discriminated external/built-in request.
      await data.eneo.mcpServers.create(
        payload as Parameters<typeof data.eneo.mcpServers.create>[0]
      );
      if (payload.purpose !== undefined && !payload.activate) notice = m.tools_saved_inactive();
    }
    await refresh();
  }

  /**
   * Adds a server built into Eneo. A capability provider (`capability` given) is activated
   * as the tenant default when `activate` is set and the message lands on its card; a general
   * server is enabled per space afterwards, like any other.
   */
  async function addBundled(
    tool: string,
    activate = false,
    capability: { purpose: string; label: () => string } | null = null
  ) {
    addingBundled = true;
    error = "";
    notice = "";
    messagePurpose = capability?.purpose ?? null;
    const name = capability ? m.mcp_auth_bundled() : bundledServerLabel(tool);
    try {
      // The row is named in the admin's language; the chat shows it next to tool calls.
      await data.eneo.mcpServers.createBundled({
        tool,
        activate,
        name: capability ? capability.label() : bundledServerLabel(tool)
      });
      if (!capability) notice = m.tools_bundled_added({ name });
      else if (activate)
        notice = m.tools_builtin_turned_on({
          capability: capability.label().toLocaleLowerCase()
        });
      else notice = m.tools_saved_inactive();
      await refresh();
    } catch (e) {
      error = getErrorMessage(e) || m.tools_bundled_add_failed({ name });
    } finally {
      addingBundled = false;
    }
  }

  async function remove(id: string) {
    await data.eneo.mcpServers.delete({ id });
    await refresh();
  }

  async function toggle(provider: Provider) {
    busy = provider.mcp_server_id;
    error = "";
    messagePurpose = null;
    try {
      if (provider.is_enabled)
        await data.eneo.mcpServers.deactivate({ id: provider.mcp_server_id });
      else await data.eneo.mcpServers.activate({ id: provider.mcp_server_id });
      await refresh();
    } catch (e) {
      error = getErrorMessage(e) || m.capability_activation_failed();
    } finally {
      busy = null;
    }
  }
</script>

{#snippet messages()}
  {#if error}<p class="text-negative-default text-sm" role="alert">{error}</p>{/if}
  {#if notice}<p class="text-secondary text-sm" role="status">{notice}</p>{/if}
{/snippet}

<svelte:head><title>Eneo.ai – {m.admin()} – {m.tools()}</title></svelte:head>
<Page.Root {tabController}>
  <Page.Header>
    <Page.Title title={m.tools()} tour="admin-tools" />
    <Page.Tabbar>
      <Page.TabTrigger tab="mcp-servers">{m.mcp_servers()}</Page.TabTrigger>
      <Page.TabTrigger tab="functions">{m.tools_functions()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="functions">
      <div class="py-6 pr-6">
        <div class="mx-auto flex w-full max-w-5xl flex-col gap-6">
          <p class="text-secondary max-w-[72ch] text-sm">{m.tools_functions_description()}</p>
          {#if messagePurpose === null}{@render messages()}{/if}
          {#each CAPABILITIES as capability (capability.purpose)}
            {@const sources = servers
              .filter((s) => s.purpose === capability.purpose)
              .sort((a, b) => Number(a.audience === "groups") - Number(b.audience === "groups"))}
            {@const active = sources.find((s) => s.is_enabled && s.audience === "everyone")}
            {@const bundled = bundledProviderFor(capability.purpose)}
            <section
              class="border-default rounded-xl border"
              aria-labelledby={"capability-" + capability.purpose}
            >
              <header
                class="border-dimmer flex flex-wrap items-start justify-between gap-4 border-b p-5"
              >
                <div class="flex items-start gap-3">
                  <capability.icon class="text-accent-default mt-1 h-5 w-5" aria-hidden="true" />
                  <div>
                    <h2 class="text-default font-semibold" id={"capability-" + capability.purpose}>
                      {capability.label()}
                    </h2>
                    {#if !active}<p class="text-secondary mt-1 text-sm">
                        {m.tools_no_default()}
                      </p>{/if}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  {#if bundled && sources.length === 0}
                    <!-- The offer below carries both ways to add a first source. -->
                  {:else if bundled?.available}
                    <!-- Two kinds of source: the one built into Eneo, or an external server. -->
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger>
                        {#snippet child({ props })}
                          <Button {...props} size="sm" disabled={addingBundled}>
                            <Plus class="size-4" />{m.tools_add_source()}<ChevronDown
                              class="size-4"
                            />
                          </Button>
                        {/snippet}
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Content align="end" class="w-80">
                        <DropdownMenu.Item
                          class="items-start py-2 whitespace-normal"
                          onSelect={() => addBundled(bundled.tool, !active, capability)}
                        >
                          <ShieldCheck class="text-accent-default mt-0.5" aria-hidden="true" />
                          <span class="flex min-w-0 flex-col gap-0.5">
                            <span class="flex items-center gap-2">
                              <span class="font-medium">{m.mcp_auth_bundled()}</span>
                              <span
                                class="bg-accent-dimmer text-accent-stronger rounded px-2 py-0.5 text-xs font-medium"
                              >
                                {m.tools_builtin_recommended()}
                              </span>
                            </span>
                            <span class="text-secondary text-xs leading-relaxed">
                              {m.tools_builtin_menu_description()}
                            </span>
                          </span>
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class="items-start py-2 whitespace-normal"
                          onSelect={() => configure(capability.purpose)}
                        >
                          <Server class="text-accent-default mt-0.5" aria-hidden="true" />
                          <span class="flex min-w-0 flex-col gap-0.5">
                            <span class="font-medium">{m.tools_source_external()}</span>
                            <span class="text-secondary text-xs leading-relaxed">
                              {m.tools_external_menu_description()}
                            </span>
                          </span>
                        </DropdownMenu.Item>
                      </DropdownMenu.Content>
                    </DropdownMenu.Root>
                  {:else}
                    <Button size="sm" onclick={() => configure(capability.purpose)}>
                      <Plus class="size-4" />{sources.length
                        ? m.tools_add_source()
                        : m.capability_configure({
                            capability: capability.label().toLocaleLowerCase()
                          })}
                    </Button>
                  {/if}
                </div>
              </header>
              {#if messagePurpose === capability.purpose && (error || notice)}
                <div class="border-dimmer border-b p-5">{@render messages()}</div>
              {/if}
              {#if bundled && sources.length === 0}
                <!-- First source: the provider built into Eneo, offered ahead of the external form. -->
                <div class="flex flex-col gap-3 p-5">
                  <div class="bg-secondary flex flex-wrap items-center gap-4 rounded-lg p-4">
                    <span
                      class="flex size-10 shrink-0 items-center justify-center rounded-lg {bundled.available
                        ? 'bg-accent-dimmer text-accent-stronger'
                        : 'bg-primary text-secondary'}"
                    >
                      <ShieldCheck class="size-5" aria-hidden="true" />
                    </span>
                    <div class="flex min-w-0 flex-1 flex-col gap-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="text-default text-sm font-semibold"
                          >{m.mcp_auth_bundled()}</span
                        >
                        {#if bundled.available}
                          <span
                            class="bg-accent-dimmer text-accent-stronger rounded px-2 py-0.5 text-xs font-medium"
                          >
                            {m.tools_builtin_recommended()}
                          </span>
                        {:else}
                          <span
                            class="bg-primary text-secondary rounded px-2 py-0.5 text-xs font-medium"
                          >
                            {m.tools_builtin_unavailable()}
                          </span>
                        {/if}
                      </div>
                      <p class="text-secondary max-w-[62ch] text-sm">
                        {#if bundled.available}
                          {capability.bundledDescription?.() ?? m.tools_builtin_menu_description()}
                        {:else}
                          {m.tools_builtin_unavailable_hint()}
                          <a
                            href={DEPLOYMENT_GUIDE_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            class="text-default font-medium underline underline-offset-2"
                          >
                            {m.tools_builtin_deployment_guide()}
                          </a>
                        {/if}
                      </p>
                    </div>
                    <Button
                      disabled={addingBundled || !bundled.available}
                      onclick={() => addBundled(bundled.tool, true, capability)}
                    >
                      {m.tools_builtin_turn_on()}
                    </Button>
                  </div>
                  <p class="text-secondary text-sm">
                    {m.tools_prefer_own_service()}
                    <button
                      type="button"
                      class="text-default font-medium underline underline-offset-2"
                      onclick={() => configure(capability.purpose)}
                    >
                      {m.tools_connect_external()}
                    </button>
                  </p>
                </div>
              {/if}
              {#each sources as source (source.mcp_server_id)}
                {@const expanded = reviewing === source.mcp_server_id}
                <div class="border-dimmer border-b p-5 last:border-b-0">
                  <div
                    class="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-4 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`${expanded ? m.governance_mcp_hide_tools() : m.governance_mcp_show_tools()}: ${source.name}`}
                      aria-expanded={expanded}
                      aria-controls={"source-tools-" + source.mcp_server_id}
                      onclick={() => (reviewing = expanded ? null : source.mcp_server_id)}
                    >
                      <ChevronRight
                        class="h-4 w-4 transition-transform duration-200 {expanded
                          ? 'rotate-90'
                          : ''}"
                        aria-hidden="true"
                      />
                    </Button>
                    <div class="min-w-0">
                      <div class="flex flex-wrap items-center gap-2">
                        <h3 class="text-default text-sm font-medium">{source.name}</h3>
                        {#if source.http_auth_type === "bundled"}
                          <span class="text-secondary bg-secondary rounded px-2 py-0.5 text-xs">
                            {m.mcp_auth_bundled()}
                          </span>
                        {/if}
                        {#if source.audience === "groups"}
                          <span class="text-secondary bg-secondary rounded px-2 py-0.5 text-xs">
                            {m.tools_group_override()}
                          </span>
                        {/if}
                      </div>
                      <p class="text-secondary mt-1 text-sm break-words">
                        {#if source.http_auth_type === "internal"}
                          {m.tools_source_model()} · {source.image_model?.nickname ||
                            source.image_model?.name ||
                            m.tools_readiness_model_missing()}
                          {#if source.image_model?.provider_name}
                            · {source.image_model.provider_name}{/if}
                        {:else if source.http_auth_type === "bundled"}
                          <!-- The runtime address is deployment plumbing; say what the provider does. -->
                          {source.description ||
                            capability.bundledDescription?.() ||
                            m.tools_builtin_menu_description()}
                        {:else}{m.tools_source_external()} · {source.http_url}{/if}
                      </p>
                      {#if source.audience === "groups"}
                        <p class="text-secondary mt-1 text-xs">
                          {(source.user_groups ?? []).map((g) => g.name).join(", ")}
                        </p>
                      {/if}
                      <div class="mt-2">
                        <span
                          class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium {source.readiness_reason
                            ? 'bg-warning-dimmer text-warning-stronger'
                            : source.is_enabled
                              ? 'bg-positive-dimmer text-positive-stronger'
                              : 'bg-secondary text-secondary'}"
                        >
                          {#if source.readiness_reason}
                            <TriangleAlert class="h-3.5 w-3.5" aria-hidden="true" />
                          {:else if source.is_enabled}
                            <CircleCheck class="h-3.5 w-3.5" aria-hidden="true" />
                          {:else}
                            <CircleDashed class="h-3.5 w-3.5" aria-hidden="true" />
                          {/if}
                          {source.readiness_reason
                            ? m.tools_blocked()
                            : source.is_enabled
                              ? m.tools_active()
                              : m.tools_inactive()}
                        </span>
                        {#if source.readiness_reason}
                          <p class="text-warning-stronger mt-2 text-sm">
                            {readinessMessage(source.readiness_reason)}
                          </p>
                        {/if}
                      </div>
                      {#if !source.is_enabled && active && source.audience === "everyone"}
                        <p class="text-secondary mt-1 text-xs">
                          {m.tools_replace_default({ name: active.name })}
                        </p>
                      {/if}
                    </div>
                    <div
                      class="col-start-2 flex flex-wrap items-center gap-2 sm:col-start-3 sm:row-start-1"
                    >
                      <DropdownMenu.Root>
                        <DropdownMenu.Trigger>
                          {#snippet child({ props })}
                            <Button
                              {...props}
                              variant="ghost"
                              size="icon"
                              class="hover:bg-hover-on-fill hover:text-primary"
                              aria-label={`${m.actions()}: ${source.name}`}
                            >
                              <IconEllipsis />
                            </Button>
                          {/snippet}
                        </DropdownMenu.Trigger>
                        <DropdownMenu.Content align="end">
                          <DropdownMenu.Item
                            disabled={busy !== null ||
                              (!source.is_enabled && !!source.readiness_reason)}
                            onSelect={() => toggle(source)}
                          >
                            {#if source.is_enabled}
                              <Pause class="h-4 w-4" aria-hidden="true" />
                            {:else}
                              <Power class="h-4 w-4" aria-hidden="true" />
                            {/if}
                            {source.is_enabled ? m.deactivate() : m.activate()}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item onSelect={() => configure(capability.purpose, source)}>
                            <Pencil class="h-4 w-4" aria-hidden="true" />{m.tools_change()}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            variant="destructive"
                            onSelect={() => {
                              deleting = source;
                              deleteOpen = true;
                            }}
                          >
                            <Trash2 class="h-4 w-4" aria-hidden="true" />{m.delete()}
                          </DropdownMenu.Item>
                        </DropdownMenu.Content>
                      </DropdownMenu.Root>
                    </div>
                  </div>
                  {#if expanded}
                    <div id={"source-tools-" + source.mcp_server_id} class="mt-4 ml-9">
                      {#if source.http_auth_type === "internal"}
                        <ProviderToolsSummary tools={source.tools ?? []} server={source} />
                      {:else}
                        <MCPToolsPanel
                          mcpServerId={source.mcp_server_id}
                          serverName={source.name}
                          tools={source.tools ?? []}
                          eneoClient={data.eneo}
                        />
                      {/if}
                    </div>
                  {/if}
                </div>
              {/each}
              {#if capability.guide && sources.length > 0}
                <!-- Usage guidance lives here and in the docs, not in assistant settings. -->
                <p class="border-dimmer text-secondary border-t p-5 text-sm">
                  {capability.guide.hint()}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- external docs link -->
                  <a
                    href={capability.guide.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-default font-medium underline underline-offset-2"
                  >
                    {capability.guide.label()}
                  </a>
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                </p>
              {/if}
            </section>
          {/each}
        </div>
      </div>
    </Page.Tab>
    <Page.Tab id="mcp-servers">
      <div class="py-6 pr-6">
        <p class="text-secondary mb-4 max-w-[72ch] text-sm">{m.tools_connections_description()}</p>
        {#if messagePurpose === null}<div class="mb-4">{@render messages()}</div>{/if}
        <MCPServersTable mcpServers={external}>
          {#snippet filters()}
            <Field.Field orientation="horizontal" class="w-auto gap-4">
              <Field.Label for={`${uid}-show-function-servers`}>
                {m.tools_show_function_servers()}
              </Field.Label>
              <Switch id={`${uid}-show-function-servers`} bind:checked={showFunctionServers} />
            </Field.Field>
          {/snippet}
          {#snippet actions()}
            {#if bundledServersToAdd.length}
              <!-- One entry point: the servers built into Eneo first, then an external one. -->
              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  {#snippet child({ props })}
                    <Button {...props} size="sm" disabled={addingBundled}>
                      <Wrench class="size-4" />{m.add_mcp_server()}<ChevronDown class="size-4" />
                    </Button>
                  {/snippet}
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end" class="w-80">
                  <DropdownMenu.Label class="text-secondary text-xs font-medium">
                    {m.mcp_auth_bundled()}
                  </DropdownMenu.Label>
                  {#each bundledServersToAdd as bundled (bundled.tool)}
                    {@const server = BUNDLED_SERVERS[bundled.tool]}
                    {@const Icon = server?.icon ?? Package}
                    <DropdownMenu.Item
                      class="items-start py-2 whitespace-normal"
                      onSelect={() => addBundled(bundled.tool)}
                    >
                      <Icon class="text-accent-default mt-0.5" aria-hidden="true" />
                      <span class="flex min-w-0 flex-col gap-0.5">
                        <span class="font-medium">{bundledServerLabel(bundled.tool)}</span>
                        {#if server}
                          <span class="text-secondary text-xs leading-relaxed">
                            {server.description()}
                          </span>
                        {/if}
                      </span>
                    </DropdownMenu.Item>
                  {/each}
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item
                    class="items-start py-2 whitespace-normal"
                    onSelect={() => configure("general")}
                  >
                    <Server class="text-accent-default mt-0.5" aria-hidden="true" />
                    <span class="flex min-w-0 flex-col gap-0.5">
                      <span class="font-medium">{m.tools_source_external()}</span>
                      <span class="text-secondary text-xs leading-relaxed">
                        {m.tools_external_menu_description()}
                      </span>
                    </span>
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            {:else}
              <Button size="sm" onclick={() => configure("general")}
                ><Wrench class="size-4" />{m.add_mcp_server()}</Button
              >
            {/if}
          {/snippet}
        </MCPServersTable>
      </div>
    </Page.Tab>
  </Page.Main>
</Page.Root>
<MCPServerDialog
  openController={open}
  mcpServer={editing}
  initialPurpose={purpose}
  onSubmit={save}
  lockPurpose
  activateOnSave
  replacesDefault={servers.find(
    (s) => s.purpose === purpose && s.is_enabled && s.audience === "everyone"
  )?.name}
/>

{#if deleting}<DeleteMCPDialog bind:open={deleteOpen} mcpServer={deleting} onDelete={remove} />{/if}
