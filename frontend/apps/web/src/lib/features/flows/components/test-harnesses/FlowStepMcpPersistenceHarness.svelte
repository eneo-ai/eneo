<script lang="ts">
  import SelectMCPServers from "$lib/features/mcp/components/SelectMCPServers.svelte";

  export let initialServers: Array<Record<string, unknown>> = [];
  export let initialTools: Array<{ tool_id: string; is_enabled: boolean }> = [];
  export let selectedModel: { supports_tool_calling?: boolean } | null = {
    supports_tool_calling: true
  };
  export let switchedServers: Array<Record<string, unknown>> = [];
  export let switchedTools: Array<{ tool_id: string; is_enabled: boolean }> = [];

  let currentAssistantId = "assistant-1";
  let selectedMCPServers = initialServers;
  let selectedMCPTools = initialTools;
  let saveCalls: Array<Record<string, unknown>> = [];

  function persistSelection(
    event: CustomEvent<{
      selectedMCPServers: Array<Record<string, unknown>>;
      selectedMCPTools: Array<{ tool_id: string; is_enabled: boolean }>;
    }>
  ) {
    saveCalls = [
      ...saveCalls,
      {
        assistantId: currentAssistantId,
        mcp_servers: event.detail.selectedMCPServers,
        mcp_tools: event.detail.selectedMCPTools
      }
    ];
  }

  function switchAssistant() {
    currentAssistantId = "assistant-2";
    selectedMCPServers = switchedServers;
    selectedMCPTools = switchedTools;
  }
</script>

<button type="button" data-testid="switch-assistant" onclick={switchAssistant}>switch</button>

<SelectMCPServers
  bind:selectedMCPServers
  bind:selectedMCPTools
  {selectedModel}
  on:change={persistSelection}
/>

<output data-testid="save-call-count">{saveCalls.length}</output>
<output data-testid="last-save">{JSON.stringify(saveCalls.at(-1) ?? null)}</output>
