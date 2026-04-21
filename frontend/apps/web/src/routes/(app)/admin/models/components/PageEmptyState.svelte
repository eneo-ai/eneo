<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { Plus, Cpu, Sparkles } from "lucide-svelte";
  import { createEventDispatcher } from "svelte";
  import { fly, fade } from "svelte/transition";

  const dispatch = createEventDispatcher<{
    addProvider: void;
  }>();

  function handleAddProvider() {
    dispatch("addProvider");
  }
</script>

<div class="flex flex-col items-center justify-center px-8 py-20" in:fade={{ duration: 300 }}>
  <!-- Decorative Icon Group -->
  <div class="relative mb-8" in:fly={{ y: 10, duration: 400, delay: 100 }}>
    <!-- Background glow -->
    <div class="bg-accent-dimmer/30 absolute inset-0 scale-150 rounded-full blur-2xl"></div>

    <!-- Main icon container -->
    <div
      class="from-surface to-surface-dimmer dark:from-accent-dimmer dark:to-accent-dimmer border-dimmer/60 dark:border-accent-default/20 relative
      flex h-24 w-24
      items-center justify-center
      rounded-2xl border bg-gradient-to-br
      shadow-sm shadow-black/5
      dark:shadow-black/20"
    >
      <Cpu class="text-muted/60 dark:text-accent-stronger h-10 w-10" strokeWidth={1.5} />

      <!-- Floating sparkle accent -->
      <div
        class="bg-accent-dimmer border-accent-default/20 absolute -top-2 -right-2 rounded-lg border p-1.5"
      >
        <Sparkles class="text-accent-default h-4 w-4" />
      </div>
    </div>
  </div>

  <!-- Text Content -->
  <div
    class="flex max-w-sm flex-col items-center gap-3 text-center"
    in:fly={{ y: 10, duration: 400, delay: 200 }}
  >
    <h3 class="text-primary text-lg font-semibold">
      {m.no_providers_title()}
    </h3>
    <p class="text-muted/80 text-sm leading-relaxed">
      {m.no_providers_description()}
    </p>
  </div>

  <!-- CTA Button -->
  <div class="mt-8" in:fly={{ y: 10, duration: 400, delay: 300 }}>
    <Button variant="primary" on:click={handleAddProvider} class="gap-2.5 px-6">
      <Plus class="-ml-0.5 h-4 w-4" />
      {m.add_first_provider()}
    </Button>
  </div>

  <!-- Helper text -->
  <p
    class="text-muted/50 mt-6 max-w-xs text-center text-[11px] tracking-wide"
    in:fly={{ y: 10, duration: 400, delay: 400 }}
  >
    {m.no_providers_helper()}
  </p>
</div>
