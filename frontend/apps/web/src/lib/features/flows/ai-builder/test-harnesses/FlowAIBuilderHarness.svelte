<script lang="ts">
  import FlowAIBuilder from "../FlowAIBuilder.svelte";
  import {
    initAIBuilderService,
    type FlowAIBuilderService
  } from "../FlowAIBuilderService.svelte.ts";
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { Space } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import type { AIBuilderClientTransport } from "../FlowAIBuilderDriver";
  import type { TargetKind } from "../protocol";

  interface Props {
    transport: AIBuilderClientTransport;
    targetKind?: TargetKind;
    flowId?: string | null;
    initialPrompt?: string | null;
    /** Test hook: receive the service instance to drive live session changes. */
    onservice?: (service: FlowAIBuilderService) => void;
  }

  let {
    transport,
    targetKind = "create",
    flowId = null,
    initialPrompt = null,
    onservice
  }: Props = $props();

  initFlowUserMode();
  untrack(() => {
    // The plan pane reads the current space (models, MCP servers); give the
    // shell harness the same minimal space the plan-pane harness uses.
    initSpacesManager({
      spaces: [],
      currentSpace: {
        id: "space-1",
        name: "Space 1",
        personal: true,
        members: { items: [] },
        applications: {
          assistants: { items: [], permissions: [] },
          group_chats: { items: [], permissions: [] },
          apps: { items: [], permissions: [] },
          services: { items: [], permissions: [] }
        },
        knowledge: {
          websites: { items: [], permissions: [] },
          groups: { items: [], permissions: [] },
          integration_knowledge_list: { items: [], permissions: [] }
        },
        completion_models: [{ can_access: true }],
        transcription_models: [],
        mcp_servers: []
      } as unknown as Space,
      eneo: {} as Parameters<typeof initSpacesManager>[0]["eneo"]
    });
    const service = initAIBuilderService({ client: transport } as never, "space-1", flowId);
    onservice?.(service);
  });
</script>

<FlowAIBuilder {targetKind} {initialPrompt} />
