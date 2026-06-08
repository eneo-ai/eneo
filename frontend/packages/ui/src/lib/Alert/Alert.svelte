<script context="module" lang="ts">
  export type AlertVariant = "info" | "warning" | "error" | "success";
</script>

<script lang="ts">
  import { IconInfo } from "@intric/icons/info";

  let className = "";
  export { className as class };
  /** Visual tone. Defaults to the neutral informational style. */
  export let variant: AlertVariant = "info";

  // Reuse the shared label-* token families (see ui/src/styles/themes/*.css) so
  // the alert inherits the same palette as labels and stays theme-aware.
  const toneClass: Record<AlertVariant, string> = {
    info: "label-info",
    warning: "label-yellow",
    error: "label-red",
    success: "label-green"
  };
</script>

<div
  class="{toneClass[
    variant
  ]} border-label-default bg-label-dimmer text-label-stronger flex items-start gap-2 rounded-md border p-2 text-sm {className}"
>
  <IconInfo size="sm" class="mt-0.5 shrink-0" />
  <div class="min-w-0 text-left"><slot /></div>
</div>
