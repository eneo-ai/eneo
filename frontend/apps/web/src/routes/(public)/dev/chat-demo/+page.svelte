<!-- eslint-disable intric/no-hardcoded-text -->
<!--
  PROTOTYPE / PLANNING DEMO — not shipped UI.

  Reachable at /dev/chat-demo. Demonstrates how the AI SDK Elements
  "Chain of Thought" UX could replace today's chat reasoning state, and how
  tool calls + the existing human-approval gate fit into it.

  Key idea: tool calls are STEPS in the reasoning trace, but a *pending
  approval* is LIFTED OUT of the collapsible into a prominent card — a blocking
  decision must never hide inside a folded "Thought for 5s" row. Once resolved,
  the tool folds back into the trace as a completed/denied step.

  See README.md for the idea sketch and rollout plan.
-->
<script lang="ts">
  import { Markdown } from "@intric/ui";
  import { onDestroy, type ComponentType } from "svelte";
  import {
    Brain,
    Search,
    GitCompare,
    Bell,
    FileText,
    ArrowUp,
    RotateCcw,
    Sparkles,
    Check,
    X
  } from "lucide-svelte";

  import ChainOfThought from "./components/ChainOfThought.svelte";
  import ChainOfThoughtStep from "./components/ChainOfThoughtStep.svelte";
  import ChainOfThoughtTool from "./components/ChainOfThoughtTool.svelte";
  import ThinkingIndicator from "$lib/features/chat/components/conversation/ThinkingIndicator.svelte";

  type Status = "pending" | "active" | "complete" | "denied";
  type Phase = "idle" | "running" | "awaiting" | "answering" | "done";

  type ReasonStep = { kind: "reason"; label: string; icon: ComponentType; sources?: string[] };
  type ToolStep = {
    kind: "tool";
    label: string;
    icon: ComponentType;
    server: string;
    args: Record<string, unknown>;
    result: string;
    needsApproval?: boolean;
  };
  type Step = ReasonStep | ToolStep;

  const question = "Vilka av våra ramavtal löper ut före Q3 — och sätt upp en bevakning på dem.";

  const steps: Step[] = [
    { kind: "reason", label: "Tolkar frågan och tidsfönstret", icon: Brain },
    {
      kind: "tool",
      label: "Söker i avtalsregistret",
      icon: Search,
      server: "intric-rag · läs",
      args: { query: "ramavtal", expires_before: "2026-07-01" },
      result: "3 avtal hittade"
    },
    {
      kind: "tool",
      label: "Korsrefererar berörda leverantörer",
      icon: GitCompare,
      server: "crm-mcp · läs",
      args: { contract_ids: ["KA-2231", "KA-2274", "KA-2298"] },
      result: "3 leverantörer"
    },
    {
      kind: "tool",
      label: "Skapar bevakning för avtalen",
      icon: Bell,
      server: "procurement-mcp · skriv",
      args: {
        contract_ids: ["KA-2231", "KA-2274", "KA-2298"],
        notify: "inkop@kommun.se",
        lead_time_days: 120
      },
      result: "Bevakning skapad",
      needsApproval: true
    },
    { kind: "reason", label: "Sammanställer svaret", icon: FileText }
  ];

  const answer = `Tre ramavtal löper ut före Q3 (2026-07-01):

| Avtal | Slutdatum | Leverantör |
| --- | --- | --- |
| Kontorsmaterial | 2026-05-31 | Staples Sverige AB |
| IT-konsulttjänster | 2026-06-15 | Cygni AB |
| Städtjänster zon 2 | 2026-06-30 | ISS Facility Services AB |

Jag har lagt upp en **bevakning** med 120 dagars ledtid och avisering till
inkop@kommun.se. Starta förnyad upphandling för IT-konsulttjänster först —
ledtiden i den kategorin är historiskt 4–5 månader.`;

  let variant = $state<"after" | "before">("after");
  let phase = $state<Phase>("idle");
  let stepStatus = $state<Status[]>([]);
  let revealed = $state("");
  let duration = $state(0);
  let cotOpen = $state(true);
  let pendingIndex = $state<number | null>(null);

  const pendingStep = $derived(pendingIndex !== null ? steps[pendingIndex] : null);

  let timers: ReturnType<typeof setTimeout>[] = [];
  const clearTimers = () => {
    timers.forEach(clearTimeout);
    timers = [];
  };

  const statusFor = (i: number): Status => stepStatus[i] ?? "pending";

  function reset() {
    clearTimers();
    phase = "idle";
    stepStatus = [];
    revealed = "";
    duration = 0;
    cotOpen = true;
    pendingIndex = null;
  }

  function advance(i: number) {
    if (i >= steps.length) {
      finishReasoning();
      return;
    }
    stepStatus[i] = "active";
    duration += 1;

    const step = steps[i];
    if (step.kind === "tool" && step.needsApproval) {
      // Blocking decision → stop the run, lift the approval out, keep trace open.
      phase = "awaiting";
      pendingIndex = i;
      cotOpen = true;
      return;
    }

    timers.push(
      setTimeout(() => {
        stepStatus[i] = "complete";
        advance(i + 1);
      }, 950)
    );
  }

  function finishReasoning() {
    phase = "answering";
    cotOpen = false; // fold the trace once thinking is done — keep it, hide it
    let i = 0;
    const stream = () => {
      if (i <= answer.length) {
        revealed = answer.slice(0, i);
        i += 3;
        timers.push(setTimeout(stream, 16));
      } else {
        revealed = answer;
        phase = "done";
      }
    };
    stream();
  }

  function approve() {
    if (pendingIndex === null) return;
    const i = pendingIndex;
    pendingIndex = null;
    phase = "running";
    timers.push(
      setTimeout(() => {
        stepStatus[i] = "complete";
        advance(i + 1);
      }, 500)
    );
  }

  function deny() {
    if (pendingIndex === null) return;
    const i = pendingIndex;
    pendingIndex = null;
    phase = "running";
    stepStatus[i] = "denied";
    timers.push(setTimeout(() => advance(i + 1), 300));
  }

  function run() {
    reset();
    phase = "running";
    cotOpen = true;
    stepStatus = steps.map(() => "pending");
    advance(0);
  }

  function switchVariant(next: "after" | "before") {
    reset();
    variant = next;
  }

  onDestroy(clearTimers);
</script>

<div class="text-primary absolute inset-0 flex flex-col overflow-y-auto">
  <div class="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 py-8">
    <!-- Header / framing -->
    <header class="mb-6">
      <div
        class="text-accent-default bg-accent-dimmer mb-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
      >
        <Sparkles class="h-3.5 w-3.5" />
        Prototyp · planering
      </div>
      <h1 class="text-primary text-2xl font-semibold">Chain of Thought i chatten</h1>
      <p class="text-secondary mt-1 text-sm">
        Idéskiss: hopfällbar resonemangs-vy där verktygsanrop är steg i tracen — men ett väntande
        godkännande lyfts ut som ett tydligt kort. Växla nuläge/förslag och tryck på skicka.
      </p>
    </header>

    <!-- Before / After toggle -->
    <div class="border-default bg-secondary mb-6 inline-flex w-fit gap-1 rounded-lg border p-1">
      <button
        type="button"
        class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors {variant === 'before'
          ? 'bg-primary text-primary shadow-sm'
          : 'text-muted hover:text-secondary'}"
        onclick={() => switchVariant("before")}
      >
        Nuläge
      </button>
      <button
        type="button"
        class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors {variant === 'after'
          ? 'bg-primary text-primary shadow-sm'
          : 'text-muted hover:text-secondary'}"
        onclick={() => switchVariant("after")}
      >
        Förslag
      </button>
    </div>

    <!-- Chat surface -->
    <div class="border-default bg-primary flex-1 rounded-2xl border p-5">
      <!-- user message -->
      <div
        class="bg-accent-dimmer text-accent-stronger mb-6 ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm"
      >
        {question}
      </div>

      <!-- assistant area -->
      {#if phase === "idle"}
        <p class="text-muted text-sm italic">Tryck på skicka-knappen för att köra demon.</p>
      {:else}
        {#if variant === "after"}
          <!-- AFTER: tools interleaved in the chain of thought -->
          <div class="border-dimmer bg-secondary/40 mb-4 rounded-xl border px-3 py-2">
            <ChainOfThought
              bind:open={cotOpen}
              streaming={phase === "running" || phase === "awaiting"}
              duration={phase === "running" || phase === "awaiting" ? undefined : duration}
            >
              {#each steps as step, i (step.label)}
                {#if step.kind === "tool"}
                  <ChainOfThoughtTool
                    label={step.label}
                    icon={step.icon}
                    server={step.server}
                    args={step.args}
                    result={step.result}
                    status={statusFor(i)}
                    last={i === steps.length - 1}
                  />
                {:else}
                  <ChainOfThoughtStep
                    label={step.label}
                    icon={step.icon}
                    status={statusFor(i)}
                    last={i === steps.length - 1}
                  />
                {/if}
              {/each}
            </ChainOfThought>
          </div>
        {:else if phase === "running" || phase === "awaiting"}
          <!-- BEFORE: today's badge — reasoning + tools are invisible -->
          <ThinkingIndicator />
        {/if}

        <!-- Lifted approval card — shown in BOTH variants, never hidden -->
        {#if phase === "awaiting" && pendingStep && pendingStep.kind === "tool"}
          <div class="border-accent-default/30 bg-accent-dimmer/40 mb-4 rounded-xl border p-4">
            <div class="flex items-start gap-3">
              <div
                class="bg-accent-default/10 text-accent-default flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
              >
                <Bell class="h-4.5 w-4.5" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-primary text-sm font-medium">{pendingStep.label}</span>
                  <span
                    class="border-default bg-primary text-muted rounded-full border px-2 py-0.5 text-xs"
                  >
                    {pendingStep.server}
                  </span>
                </div>
                <p class="text-secondary mt-1 text-sm">
                  Det här verktyget utför en åtgärd och kräver ditt godkännande.
                </p>
                <pre
                  class="bg-primary/60 text-secondary mt-2 overflow-x-auto rounded-md p-2.5 font-mono text-xs whitespace-pre-wrap">{JSON.stringify(
                    pendingStep.args,
                    null,
                    2
                  )}</pre>
              </div>
            </div>
            <div class="mt-3 flex justify-end gap-2">
              <button
                type="button"
                class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors"
                onclick={approve}
              >
                <Check class="h-3.5 w-3.5" />
                Godkänn
              </button>
              <button
                type="button"
                class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium shadow-sm transition-colors"
                onclick={deny}
              >
                <X class="h-3.5 w-3.5" />
                Neka
              </button>
            </div>
          </div>
        {/if}

        {#if revealed}
          <div class="prose max-w-none text-sm">
            <Markdown source={revealed} />
          </div>
        {/if}
      {/if}
    </div>

    <!-- composer -->
    <div
      class="border-default bg-primary mt-4 flex items-center gap-2 rounded-2xl border px-4 py-2.5"
    >
      <span class="text-muted flex-1 truncate text-sm">{question}</span>
      {#if phase === "idle"}
        <button
          type="button"
          class="bg-accent-default text-on-fill hover:bg-accent-stronger flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors"
          aria-label="Skicka"
          onclick={run}
        >
          <ArrowUp class="h-5 w-5" />
        </button>
      {:else}
        <button
          type="button"
          class="border-default bg-secondary text-secondary hover:bg-hover-default flex h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors"
          onclick={reset}
        >
          <RotateCcw class="h-4 w-4" />
          Kör om
        </button>
      {/if}
    </div>
  </div>
</div>
