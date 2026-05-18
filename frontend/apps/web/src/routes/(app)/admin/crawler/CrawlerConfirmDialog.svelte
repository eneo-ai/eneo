<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<!--
  Shared confirmation dialog for the crawler admin surface.

  All confirm/cancel modals on /admin/crawler funnel through this primitive
  so the shape, spacing, and target-pill treatment stay identical: a neutral
  description ("…the website below"), an optional mono pill that anchors the
  identifier (URL or job id), an optional extras snippet for inputs/selects/
  alerts, and a footer with a single cancel + a single primary action.
-->

<script lang="ts">
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import type { ButtonVariant } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Snippet } from "svelte";

  type Props = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description: string;
    /**
     * URL or stable identifier shown as a styled mono pill below the
     * description. Anchors the dialog to a single subject and keeps the
     * description text free of inline URLs that wrap badly. Optional;
     * omit when the dialog has no single subject.
     */
    target?: string | null;
    /**
     * Confirm-button variant. Use "destructive" for delete/abort, the
     * default "default" elsewhere. Cancel always uses the outline variant
     * for parity with the rest of the AlertDialog system.
     */
    variant?: ButtonVariant;
    confirmLabel: string;
    /** Label shown on the confirm button while `busy` is true. */
    busyLabel: string;
    /** Defaults to the shared `cancel` message. */
    cancelLabel?: string;
    busy: boolean;
    /**
     * Extra gating on top of `busy` (e.g. delete dialog requires the
     * operator to type the URL exactly). Confirm is disabled while busy
     * regardless of this prop.
     */
    confirmDisabled?: boolean;
    onConfirm: () => void;
    /** Optional extras: input row, select, alert callout. */
    children?: Snippet;
  };

  const {
    open,
    onOpenChange,
    title,
    description,
    target = null,
    variant = "default",
    confirmLabel,
    busyLabel,
    cancelLabel,
    busy,
    confirmDisabled = false,
    onConfirm,
    children
  }: Props = $props();

  const resolvedCancelLabel = $derived(cancelLabel ?? m.cancel());
  const isDestructive = $derived(variant === "destructive");

  /**
   * Pill styling tracks the action's tone. Destructive actions get a
   * subtle danger-tinted border + fill so the operator's eye associates
   * the identifier with what is about to be removed. Neutral actions
   * use the standard muted surface treatment.
   *
   * `select-all` lets the operator click once to select the entire
   * identifier, useful when they need to compare it against another
   * source or paste it into the retype-to-confirm input.
   */
  const pillClass = $derived(
    isDestructive
      ? "border-destructive/30 bg-destructive/5 text-foreground mt-2 block cursor-text rounded-md border px-2.5 py-1.5 font-mono text-xs break-all select-all"
      : "border-border/60 bg-muted/30 text-foreground mt-2 block cursor-text rounded-md border px-2.5 py-1.5 font-mono text-xs break-all select-all"
  );
</script>

<AlertDialog.Root {open} {onOpenChange}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{title}</AlertDialog.Title>
      <AlertDialog.Description class="text-left">
        {description}
        {#if target}
          <span class={pillClass} title={target}>
            {target}
          </span>
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>

    {@render children?.()}

    <AlertDialog.Footer class="bg-popover">
      <AlertDialog.Cancel disabled={busy}>
        {resolvedCancelLabel}
      </AlertDialog.Cancel>
      <AlertDialog.Action {variant} disabled={busy || confirmDisabled} onclick={onConfirm}>
        {busy ? busyLabel : confirmLabel}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
