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

<div
  class="flex flex-col items-center justify-center py-20 px-8"
  in:fade={{ duration: 300 }}
>
  <!-- Decorative Icon Group -->
  <div class="relative mb-8" in:fly={{ y: 10, duration: 400, delay: 100 }}>
    <!-- Background glow -->
    <div class="absolute inset-0 bg-accent-dimmer/30 blur-2xl rounded-full scale-150"></div>

    <!-- Main icon container -->
    <div class="relative flex items-center justify-center w-24 h-24 rounded-2xl
      bg-gradient-to-br from-surface to-surface-dimmer
      border border-dimmer/60
      shadow-sm shadow-black/5
      dark:shadow-black/20">
      <Cpu class="w-10 h-10 text-muted/60" strokeWidth={1.5} />

      <!-- Floating sparkle accent -->
      <div class="absolute -top-2 -right-2 p-1.5 rounded-lg bg-accent-dimmer border border-accent-default/20">
        <Sparkles class="w-4 h-4 text-accent-default" />
      </div>
    </div>
  </div>

  <!-- Text Content -->
  <div class="flex flex-col items-center text-center max-w-sm gap-3" in:fly={{ y: 10, duration: 400, delay: 200 }}>
    <h3 class="text-lg font-semibold text-primary">
      {m.no_providers_title()}
    </h3>
    <p class="text-sm text-muted/80 leading-relaxed">
      {m.no_providers_description()}
    </p>
  </div>

  <!-- CTA Button -->
  <div class="mt-8" in:fly={{ y: 10, duration: 400, delay: 300 }}>
    <Button variant="primary" on:click={handleAddProvider} class="gap-2.5 px-6">
      <Plus class="w-4 h-4 -ml-0.5" />
      {m.add_first_provider()}
    </Button>
  </div>

  <!-- Helper text -->
  <p
    class="mt-6 text-[11px] text-muted/50 max-w-xs text-center tracking-wide"
    in:fly={{ y: 10, duration: 400, delay: 400 }}
  >
    {m.no_providers_helper()}
  </p>
</div>
