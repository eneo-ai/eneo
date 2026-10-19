<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  The step an admin lands on right after saving an OAuth server: the save is
  done, the connection is next, and the tools follow by themselves. Shown as
  a three-step list so the admin sees where they are and what the popup is
  going to do before it opens.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Check, LoaderCircle, Plug, Wrench } from "@lucide/svelte";

  let {
    serverName,
    shared = false,
    connecting = false,
    syncing = false
  }: {
    serverName: string;
    /** A shared server is connected as the vendor's service account. */
    shared?: boolean;
    /** The vendor's window is open and the admin is approving. */
    connecting?: boolean;
    /** The connection is made and the tools are being fetched. */
    syncing?: boolean;
  } = $props();

  type Tone = "done" | "current" | "next";
  const steps = $derived<
    { title: string; hint: string; tone: Tone; icon: typeof Check; busy: boolean }[]
  >([
    {
      title: m.mcp_oauth_step_saved(),
      hint: serverName,
      tone: "done",
      icon: Check,
      busy: false
    },
    {
      title: m.mcp_oauth_step_connect(),
      hint: connecting
        ? m.mcp_oauth_step_connect_waiting()
        : shared
          ? m.mcp_oauth_step_connect_shared_hint()
          : m.mcp_oauth_step_connect_hint({ server: serverName }),
      tone: syncing ? "done" : "current",
      icon: syncing ? Check : Plug,
      busy: connecting
    },
    {
      title: m.mcp_oauth_step_tools(),
      hint: syncing ? m.mcp_oauth_step_tools_syncing() : m.mcp_oauth_step_tools_hint(),
      tone: syncing ? "current" : "next",
      icon: Wrench,
      busy: syncing
    }
  ]);

  const badge: Record<Tone, string> = {
    done: "bg-positive-dimmer text-positive-default",
    current: "bg-accent-dimmer text-accent-default ring-accent-default/30 ring-2",
    next: "bg-secondary text-muted"
  };
</script>

<ol class="flex flex-col" aria-label={m.mcp_oauth_connect_step_heading({ server: serverName })}>
  {#each steps as step, i (step.title)}
    <li class="flex gap-4" aria-current={step.tone === "current" ? "step" : undefined}>
      <div class="flex flex-col items-center">
        <span
          class="flex size-9 shrink-0 items-center justify-center rounded-full {badge[step.tone]}"
          aria-hidden="true"
        >
          {#if step.busy}
            <LoaderCircle class="size-4 animate-spin" />
          {:else}
            <step.icon class="size-4" />
          {/if}
        </span>
        {#if i < steps.length - 1}
          <span
            class="my-1 w-px flex-1 {step.tone === 'done' ? 'bg-positive-default/40' : 'bg-dimmer'}"
            aria-hidden="true"
          ></span>
        {/if}
      </div>
      <div class="flex min-w-0 flex-col gap-0.5 pb-6 pt-1.5">
        <span class="text-sm font-medium {step.tone === 'next' ? 'text-muted' : 'text-default'}">
          {step.title}
        </span>
        <span class="text-secondary text-sm leading-relaxed">{step.hint}</span>
      </div>
    </li>
  {/each}
</ol>
