<script lang="ts">
  import type { Snippet } from "svelte";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Plug from "@lucide/svelte/icons/plug";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import { toolRefusalSentence } from "$lib/features/flows/flowToolRefusal";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  let {
    actions
  }: {
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
</script>

<Empty.Root class="border">
  <Empty.Header>
    <Empty.Media variant="icon">
      <Plug aria-hidden="true" />
    </Empty.Media>
    <Empty.Title>{m.flow_tool_options_empty()}</Empty.Title>
    <Empty.Description>
      {#if personal}
        {toolRefusalSentence("space_is_personal")}
      {:else}
        {m.flow_tool_options_empty_lead()}
      {/if}
    </Empty.Description>
  </Empty.Header>
  <Empty.Content>
    {#if !personal}
      <ol
        class="text-muted-foreground flex list-decimal flex-col gap-1.5 self-stretch pl-5 text-left text-sm/relaxed"
      >
        <li>{m.flow_tool_options_empty_step_server()}</li>
        <li>
          {mayEditSpace ? m.flow_tool_options_empty_editor() : m.flow_tool_options_empty_admin()}
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
    {@render actions?.()}
  </Empty.Content>
</Empty.Root>
