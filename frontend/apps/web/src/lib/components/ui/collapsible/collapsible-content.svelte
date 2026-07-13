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

  /*
    Opt-in height animation: pass class="collapsible-animate". bits-ui blocks
    the animation on initial mount (isMountAnimationPrevented) and its
    presence layer keeps closing content mounted until the animation ends,
    so both directions play. Content that must overflow while open (menus,
    popovers) should not opt in — the element clips during and after.
  */
  :global([data-slot="collapsible-content"].collapsible-animate) {
    overflow: hidden;
  }

  :global([data-slot="collapsible-content"].collapsible-animate[data-state="open"]) {
    animation: collapsible-open 200ms cubic-bezier(0.25, 1, 0.5, 1);
  }

  :global([data-slot="collapsible-content"].collapsible-animate[data-state="closed"]) {
    animation: collapsible-close 150ms cubic-bezier(0.25, 1, 0.5, 1);
  }

  @keyframes -global-collapsible-open {
    from {
      height: 0;
    }
    to {
      height: var(--bits-collapsible-content-height);
    }
  }

  @keyframes -global-collapsible-close {
    from {
      height: var(--bits-collapsible-content-height);
    }
    to {
      height: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    :global([data-slot="collapsible-content"].collapsible-animate[data-state="open"]),
    :global([data-slot="collapsible-content"].collapsible-animate[data-state="closed"]) {
      animation: none;
    }
  }
</style>
