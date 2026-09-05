<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button, Dropdown, Input } from "@eneo/ui";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { invalidate } from "$app/navigation";
  import { writable } from "svelte/store";
  import { untrack } from "svelte";
  import {
    Plus,
    Wrench,
    CheckCircle2,
    CircleDashed,
    AlertTriangle,
    Power,
    Pause,
    Pencil,
    Trash2,
    ChevronRight
  } from "lucide-svelte";
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
  setSecurityContext(untrack(() => data.securityClassifications));
  const open = writable(false);
  const tabController = writable("functions");
  const deleteOpen = writable(false);
  let deleting = $state<Provider | null>(null);
  let purpose = $state("general");
  let editing = $state<Provider | null>(null);
  let busy = $state<string | null>(null);
  let error = $state("");
  let notice = $state("");
  let reviewing = $state<string | null>(null);
  const servers = $derived(data.mcpSettings.items ?? []);
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

  async function remove(id: string) {
    await data.eneo.mcpServers.delete({ id });
    await refresh();
  }

  async function toggle(provider: Provider) {
    busy = provider.mcp_server_id;
    error = "";
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

<svelte:head><title>Eneo.ai – {m.admin()} – {m.tools()}</title></svelte:head>
<Page.Root {tabController}>
  <Page.Header>
    <Page.Title title={m.tools()} />
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
          {#if error}<p class="text-negative-default" role="alert">{error}</p>{/if}
          {#if notice}<p class="text-secondary text-sm" role="status">{notice}</p>{/if}
          {#each CAPABILITIES as capability (capability.purpose)}
            {@const sources = servers
              .filter((s) => s.purpose === capability.purpose)
              .sort((a, b) => Number(a.audience === "groups") - Number(b.audience === "groups"))}
            {@const active = sources.find((s) => s.is_enabled && s.audience === "everyone")}
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
                <Button size="sm" variant="primary" onclick={() => configure(capability.purpose)}>
                  <Plus class="mr-2 h-4 w-4" />{sources.length
                    ? m.tools_add_source()
                    : m.capability_configure({
                        capability: capability.label().toLocaleLowerCase()
                      })}
                </Button>
              </header>
              {#each sources as source (source.mcp_server_id)}
                {@const expanded = reviewing === source.mcp_server_id}
                <div class="border-dimmer border-b p-5 last:border-b-0">
                  <div
                    class="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-4 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
                  >
                    <Button
                      variant="simple"
                      padding="icon"
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
                            <AlertTriangle class="h-3.5 w-3.5" aria-hidden="true" />
                          {:else if source.is_enabled}
                            <CheckCircle2 class="h-3.5 w-3.5" aria-hidden="true" />
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
                      <Button
                        size="sm"
                        variant={source.is_enabled ? "warning-outlined" : "positive"}
                        disabled={busy !== null ||
                          (!source.is_enabled && !!source.readiness_reason)}
                        onclick={() => toggle(source)}
                      >
                        {#if source.is_enabled}
                          <Pause class="h-4 w-4" aria-hidden="true" />
                        {:else}
                          <Power class="h-4 w-4" aria-hidden="true" />
                        {/if}
                        {source.is_enabled ? m.deactivate() : m.activate()}
                      </Button>
                      <Dropdown.Root>
                        <Dropdown.Trigger let:trigger asFragment>
                          <Button
                            is={trigger}
                            variant="on-fill"
                            padding="icon"
                            aria-label={`${m.actions()}: ${source.name}`}
                          >
                            <IconEllipsis />
                          </Button>
                        </Dropdown.Trigger>
                        <Dropdown.Menu let:item>
                          <Button
                            is={item}
                            padding="icon-leading"
                            onclick={() => configure(capability.purpose, source)}
                          >
                            <Pencil class="h-4 w-4" aria-hidden="true" />{m.tools_change()}
                          </Button>
                          <Button
                            is={item}
                            padding="icon-leading"
                            variant="destructive"
                            onclick={() => {
                              deleting = source;
                              deleteOpen.set(true);
                            }}
                          >
                            <Trash2 class="h-4 w-4" aria-hidden="true" />{m.delete()}
                          </Button>
                        </Dropdown.Menu>
                      </Dropdown.Root>
                    </div>
                  </div>
                  {#if expanded}
                    <div id={"source-tools-" + source.mcp_server_id} class="mt-4 ml-9">
                      {#if source.http_auth_type === "internal"}
                        <ProviderToolsSummary tools={source.tools ?? []} />
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
            </section>
          {/each}
        </div>
      </div>
    </Page.Tab>
    <Page.Tab id="mcp-servers">
      <div class="py-6 pr-6">
        <p class="text-secondary mb-4 max-w-[72ch] text-sm">{m.tools_connections_description()}</p>
        <MCPServersTable mcpServers={external}>
          {#snippet filters()}
            <Input.Switch bind:value={showFunctionServers} class="border-0 p-0 text-sm">
              {m.tools_show_function_servers()}
            </Input.Switch>
          {/snippet}
          {#snippet actions()}
            <Button size="sm" variant="primary" onclick={() => configure("general")}
              ><Wrench class="mr-2 h-4 w-4" />{m.add_mcp_server()}</Button
            >
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

{#if deleting}<DeleteMCPDialog
    openController={deleteOpen}
    mcpServer={deleting}
    onDelete={remove}
  />{/if}
