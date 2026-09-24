<script lang="ts">
  import type { Snippet } from "svelte";
  import { CircleAlert, CircleCheck, Clock } from "@lucide/svelte";
  import * as Card from "$lib/components/ui/card";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { cn } from "$lib/utils";

  type Tone = "success" | "warning" | "error";

  const toneBadge: Record<Tone, string> = {
    success: "bg-positive-dimmer text-positive-stronger",
    warning: "bg-warning-dimmer text-warning-stronger",
    error: "bg-negative-dimmer text-negative-stronger"
  };

  const toneIcons = {
    success: CircleCheck,
    warning: Clock,
    error: CircleAlert
  };

  let {
    title,
    description,
    tone,
    size = "sm",
    children,
    footer
  }: {
    title: string;
    description?: string;
    tone?: Tone;
    size?: "sm" | "md";
    children: Snippet;
    footer?: Snippet;
  } = $props();

  const ToneIcon = $derived(tone ? toneIcons[tone] : null);
</script>

<main class="flex min-h-svh w-full flex-col items-center justify-center gap-6 px-4 py-10">
  <EneoWordMark class="text-brand-eneo h-8 w-auto" />

  <Card.Root class={cn("w-full", size === "md" ? "max-w-md" : "max-w-sm")}>
    <Card.Header class="items-center text-center">
      {#if ToneIcon && tone}
        <div
          class={cn(
            "mb-2 flex size-12 items-center justify-center justify-self-center rounded-full",
            toneBadge[tone]
          )}
        >
          <ToneIcon aria-hidden="true" class="size-6" />
        </div>
      {/if}
      <Card.Title>
        <h1 class="text-xl font-semibold">{title}</h1>
      </Card.Title>
      {#if description}
        <Card.Description>{description}</Card.Description>
      {/if}
    </Card.Header>
    <Card.Content class="flex flex-col gap-4">
      {@render children()}
    </Card.Content>
  </Card.Root>

  {#if footer}
    <div class="flex flex-col items-center gap-2 text-sm">
      {@render footer()}
    </div>
  {/if}
</main>
