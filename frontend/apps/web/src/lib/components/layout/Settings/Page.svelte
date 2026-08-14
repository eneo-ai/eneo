<script lang="ts">
  export let density: "default" | "compact" = "default";
</script>

<div
  class="mx-auto w-full max-w-[1180px]"
  class:settings-page-default={density === "default"}
  class:settings-page-compact={density === "compact"}
>
  <slot />
</div>

<style>
  .settings-page-default {
    padding-top: 2.5rem;
    padding-top: min(calc((100cqw - 1180px) * 0.35), 2.5rem);
  }

  .settings-page-compact {
    padding-top: 1rem;
  }
</style>
