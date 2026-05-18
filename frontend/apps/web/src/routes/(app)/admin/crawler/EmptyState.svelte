<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import type { Snippet } from "svelte";

  type Props = {
    title: string;
    description?: string;
    icon?: Snippet;
    actions?: Snippet;
  };

  const { title, description, icon, actions }: Props = $props();
</script>

<div
  class="border-border bg-muted/15 text-muted-foreground flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center"
  role="status"
>
  {#if icon}
    <div
      class="bg-muted/40 text-foreground/70 flex size-10 items-center justify-center rounded-full"
      aria-hidden="true"
    >
      {@render icon()}
    </div>
  {/if}
  <p class="text-foreground text-sm font-medium">{title}</p>
  {#if description}
    <p class="text-muted-foreground max-w-[42ch] text-xs leading-relaxed">{description}</p>
  {/if}
  {#if actions}
    <div class="mt-1 flex items-center gap-2">
      {@render actions()}
    </div>
  {/if}
</div>
