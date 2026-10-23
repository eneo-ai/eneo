<script lang="ts">
  import { getMessageContext } from "../MessageContext.svelte";
  import McpAppFrame from "./McpAppFrame.svelte";
  import { appViewCalls, toolCallsOf } from "./mcpApps";

  const { current, isLoading, isLast } = getMessageContext();

  // Interactive views (MCP Apps): HTML an approved tool brings, shown in a
  // sandboxed frame under the answer. A view belongs to one tool call and is
  // there from the moment the model starts writing the call.
  const calls = $derived(appViewCalls(toolCallsOf(current())));
  const live = $derived(isLoading() && isLast());
</script>

{#each calls as call (call.tool_call_id)}
  <McpAppFrame {call} {live} />
{/each}
