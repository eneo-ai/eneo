<!-- eslint-disable intric/no-hardcoded-text -->
<!--
  PROTOTYPE / PREVIEW — not shipped UI. Reachable at /dev/reasoning-preview.

  Live preview of the REAL production components now wired into chat
  (ReasoningTrace + ReasoningToolStep in lib/features/chat/components/conversation).
  Lets you see the exact in-chat behaviour — auto-collapse, running spinner,
  denied state, args expand — without needing a tool-using assistant to fire a
  real MCP call. The chat integration lives in MessageAnswer.svelte.
-->
<script lang="ts">
  import ReasoningTrace from "$lib/features/chat/components/conversation/ReasoningTrace.svelte";

  let working = $state(true);
  let denyLast = $state(false);

  const steps = $derived([
    {
      toolName: "search_contracts",
      serverName: "intric-rag",
      args: { query: "ramavtal", expires_before: "2026-07-01" },
      status: "complete" as const
    },
    {
      toolName: "list_suppliers",
      serverName: "crm-mcp",
      args: { contract_ids: ["KA-2231", "KA-2274", "KA-2298"] },
      status: "complete" as const
    },
    {
      toolName: "create_watch",
      serverName: "procurement-mcp",
      args: { notify: "inkop@kommun.se", lead_time_days: 120 },
      status: (denyLast ? "denied" : working ? "running" : "complete") as
        | "running"
        | "complete"
        | "denied"
    }
  ]);
</script>

<div class="text-primary absolute inset-0 overflow-y-auto">
  <div class="mx-auto w-full max-w-2xl px-4 py-8">
    <h1 class="text-primary mb-1 text-2xl font-semibold">ReasoningTrace — live preview</h1>
    <p class="text-secondary mb-6 text-sm">
      Riktig produktionskomponent (samma som i chatten). Växla läge för att se beteendet.
    </p>

    <div class="mb-6 flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-md border px-3 py-1.5 text-sm font-medium transition-colors {working &&
        !denyLast
          ? 'border-accent-default bg-accent-dimmer text-accent-stronger'
          : 'border-default bg-secondary text-muted hover:text-secondary'}"
        onclick={() => {
          working = true;
          denyLast = false;
        }}
      >
        Arbetar (öppen)
      </button>
      <button
        type="button"
        class="rounded-md border px-3 py-1.5 text-sm font-medium transition-colors {!working &&
        !denyLast
          ? 'border-accent-default bg-accent-dimmer text-accent-stronger'
          : 'border-default bg-secondary text-muted hover:text-secondary'}"
        onclick={() => {
          working = false;
          denyLast = false;
        }}
      >
        Klar (hopfälld)
      </button>
      <button
        type="button"
        class="rounded-md border px-3 py-1.5 text-sm font-medium transition-colors {denyLast
          ? 'border-negative-default bg-negative-dimmer text-negative-default'
          : 'border-default bg-secondary text-muted hover:text-secondary'}"
        onclick={() => {
          working = false;
          denyLast = true;
        }}
      >
        Sista nekad
      </button>
    </div>

    <!-- Mimics the assistant message context in chat -->
    <div class="border-default bg-primary rounded-2xl border p-5">
      <div
        class="bg-accent-dimmer text-accent-stronger mb-6 ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm"
      >
        Vilka ramavtal löper ut före Q3 — och sätt upp en bevakning.
      </div>

      <ReasoningTrace {steps} {working} />

      {#if !working}
        <div class="prose mt-4 max-w-none text-sm">
          <p>Tre ramavtal löper ut före Q3. Jag har sammanställt dem nedan…</p>
        </div>
      {/if}
    </div>
  </div>
</div>
