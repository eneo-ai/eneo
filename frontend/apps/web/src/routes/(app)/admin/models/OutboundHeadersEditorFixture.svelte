<script lang="ts">
  import type { OutboundHeaderOptions, OutboundHeaderPublic } from "@eneo/eneo-js";
  import OutboundHeadersEditor from "./OutboundHeadersEditor.svelte";
  import { headersPayload, rowsFromHeaders, type HeaderRow } from "./outboundHeaders";

  // Test-only fixture: owns the rows the way ProviderDialog does, and reports
  // the payload a save would send.
  let {
    providerType = "hosted_vllm",
    options,
    headers = [],
    endpoint = "",
    optionsError = false,
    onRetry,
    editing = false,
    onPayload
  }: {
    providerType?: string;
    options: OutboundHeaderOptions | null;
    headers?: OutboundHeaderPublic[];
    endpoint?: string;
    optionsError?: boolean;
    onRetry?: () => void;
    editing?: boolean;
    onPayload?: (payload: ReturnType<typeof headersPayload>) => void;
  } = $props();

  // svelte-ignore state_referenced_locally
  let rows = $state<HeaderRow[]>(rowsFromHeaders(headers));

  $effect(() => {
    onPayload?.(headersPayload(rows));
  });
</script>

<OutboundHeadersEditor
  {providerType}
  {options}
  bind:rows
  idPrefix="test-header"
  {endpoint}
  {optionsError}
  {onRetry}
  {editing}
/>
