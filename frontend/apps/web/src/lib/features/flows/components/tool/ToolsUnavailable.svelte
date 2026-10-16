<script lang="ts">
  import type { Snippet } from "svelte";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Plug from "@lucide/svelte/icons/plug";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import {
    toolRefusalSentence,
    unusableToolSentence,
    type UnusableTool
  } from "$lib/features/flows/flowToolRefusal";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  let {
    surface,
    unusable = null,
    actions
  }: {
    /** Where the reader comes back to once a tool is available: the step
     *  editor's list, or the AI Builder asked again. */
    surface: "step_editor" | "builder";
    /** The tool the reader asked for and why it cannot be used; null when
     *  the space simply offers no tool. */
    unusable?: UnusableTool | null;
    actions?: Snippet;
  } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  // A personal space can have no tools, so the steps that give one tools are
  // left out. The settings link needs the permission the space menu asks for
  // its Settings entry.
  const personal = $derived($currentSpace.personal);
  const mayEditSpace = $derived(!personal && $currentSpace.hasPermission("edit", "space"));

  const reason = $derived(unusable === null ? null : unusableToolSentence(unusable));
  // The steps say how a space gets a tool; they cannot fix a tool whose
  // schema no flow can read, nor a personal space.
  const showsSteps = $derived(
    !personal &&
      (unusable === null ||
        (unusable.kind === "refused" && unusable.refusal !== "space_is_personal"))
  );
</script>

<Empty.Root
  class={unusable === null ? "border" : "border-warning-default/40 bg-warning-dimmer border"}
>
  <Empty.Header>
    <Empty.Media variant="icon">
      {#if unusable === null}
        <Plug aria-hidden="true" />
      {:else}
        <TriangleAlert class="text-warning-stronger" aria-hidden="true" />
      {/if}
    </Empty.Media>
    <Empty.Title>
      {unusable === null
        ? m.flow_tool_options_empty()
        : m.flow_tool_unavailable_title({ tool: unusable.tool_name, server: unusable.server_name })}
    </Empty.Title>
    <Empty.Description>
      {#if reason !== null}
        {reason}
      {:else if personal}
        {toolRefusalSentence("space_is_personal")}
      {:else}
        {m.flow_tool_options_empty_lead()}
      {/if}
    </Empty.Description>
  </Empty.Header>
  <Empty.Content>
    {#if showsSteps}
      {#if reason !== null}
        <p class="text-primary self-stretch text-left text-sm font-medium">
          {m.flow_tool_options_empty_lead()}
        </p>
      {/if}
      <ol
        class="text-muted-foreground flex list-decimal flex-col gap-1.5 self-stretch pl-5 text-left text-sm/relaxed"
      >
        <li>{m.flow_tool_options_empty_step_server()}</li>
        <li>
          {mayEditSpace ? m.flow_tool_options_empty_editor() : m.flow_tool_options_empty_admin()}
        </li>
        <li>
          {surface === "builder"
            ? m.flow_tool_unavailable_step_ask_again()
            : m.flow_tool_options_empty_step_listed()}
        </li>
      </ol>
    {/if}
    {#if mayEditSpace}
      <!-- A new tab: leaving the editor saves the flow first, which a
           tool step without a tool cannot be, and the AI Builder's
           conversation stays where it is. -->
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
    {@render actions?.()}
  </Empty.Content>
</Empty.Root>
