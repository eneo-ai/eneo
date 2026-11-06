<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import Plus from "@lucide/svelte/icons/plus";
  import Cpu from "@lucide/svelte/icons/cpu";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import { fly, fade } from "svelte/transition";

  let {
    onAddProvider,
    href,
    title,
    description,
    ctaLabel,
    helper
  }: {
    /** Without it there is no call to action (nothing an admin can add here). */
    onAddProvider?: () => void;
    /** Where the action leads instead, for what is not added on this page. */
    href?: string;
    title?: string;
    description?: string;
    ctaLabel?: string;
    helper?: string;
  } = $props();
</script>

<div class="flex flex-col items-center justify-center px-8 py-20" in:fade={{ duration: 300 }}>
  <!-- Decorative Icon Group -->
  <div class="relative mb-8" in:fly={{ y: 10, duration: 400, delay: 100 }}>
    <div class="bg-accent-dimmer/30 absolute inset-0 scale-150 rounded-full blur-2xl"></div>
    <div
      class="from-primary to-secondary dark:from-accent-dimmer dark:to-accent-dimmer border-dimmer/60 dark:border-accent-default/20 relative
      flex h-24 w-24
      items-center justify-center
      rounded-2xl border bg-gradient-to-br
      shadow-sm shadow-black/5
      dark:shadow-black/20"
    >
      <Cpu class="text-muted/60 dark:text-accent-stronger h-10 w-10" strokeWidth={1.5} />
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
      {title ?? m.no_providers_title()}
    </h3>
    <p class="text-muted/80 text-sm leading-relaxed">
      {description ?? m.no_providers_description()}
    </p>
  </div>

  <!-- CTA Button -->
  {#if href}
    <div class="mt-8" in:fly={{ y: 10, duration: 400, delay: 300 }}>
      <Button {href} class="px-6">{ctaLabel}</Button>
    </div>
  {:else if onAddProvider}
    <div class="mt-8" in:fly={{ y: 10, duration: 400, delay: 300 }}>
      <Button onclick={onAddProvider} class="px-6">
        <Plus />
        {ctaLabel ?? m.add_first_provider()}
      </Button>
    </div>
  {/if}

  {#if helper !== ""}
    <p
      class="text-muted/50 mt-6 max-w-xs text-center text-[11px] tracking-wide"
      in:fly={{ y: 10, duration: 400, delay: 400 }}
    >
      {helper ?? m.no_providers_helper()}
    </p>
  {/if}
</div>
