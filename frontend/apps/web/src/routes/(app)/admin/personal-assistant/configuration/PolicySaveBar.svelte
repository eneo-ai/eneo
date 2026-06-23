<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { AlertCircle, CheckCircle2 } from "lucide-svelte";

  type Props = {
    dirty: boolean;
    saveError: string | null;
    canSave: boolean;
    saving: boolean;
    onDiscard: () => void;
    onSave: () => void;
  };

  let { dirty, saveError, canSave, saving, onDiscard, onSave }: Props = $props();
</script>

{#if dirty || saveError}
  <div
    class="border-default bg-primary fixed right-0 bottom-0 left-0 z-50 border-t shadow-lg md:left-[17rem]"
    role="region"
    aria-label={m.governance_unsaved_changes_aria()}
  >
    <div class="mx-auto flex max-w-[1100px] items-center justify-between gap-4 px-6 py-3">
      <div class="flex items-center gap-2 text-sm">
        {#if saveError}
          <AlertCircle class="text-destructive h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-destructive" role="alert">{saveError}</span>
        {:else if !canSave}
          <AlertCircle class="text-warning-stronger h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-secondary">{m.governance_fix_validation()}</span>
        {:else}
          <CheckCircle2 class="text-accent-default h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-secondary">{m.governance_unsaved_changes()}</span>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        <Button variant="ghost" onclick={onDiscard} disabled={saving}>{m.reset()}</Button>
        <Button onclick={onSave} disabled={!canSave || saving} aria-busy={saving}>
          {saving ? m.governance_saving() : m.governance_save_changes()}
        </Button>
      </div>
    </div>
  </div>
{/if}
