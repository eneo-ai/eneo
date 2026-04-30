<script lang="ts">
  import { Collapsible as CollapsiblePrimitive } from "bits-ui";

  let { ref = $bindable(null), ...restProps }: CollapsiblePrimitive.ContentProps = $props();
</script>

<CollapsiblePrimitive.Content bind:ref data-slot="collapsible-content" {...restProps} />

<!--
  bits-ui sets `--bits-collapsible-content-height` from getBoundingClientRect
  inside afterTick. Until that first measurement lands, the variable is
  undefined; if a CSS keyframe (or a downstream consumer) reads it before
  measurement, the browser logs `Invalid keyframe value for property height:
  NaNpx`. A 0px CSS default keeps the keyframe valid; bits-ui's inline style
  wins via specificity once the real height is measured.
-->
<style>
  :global([data-slot="collapsible-content"]) {
    --bits-collapsible-content-height: 0px;
    --bits-collapsible-content-width: 0px;
  }
</style>
