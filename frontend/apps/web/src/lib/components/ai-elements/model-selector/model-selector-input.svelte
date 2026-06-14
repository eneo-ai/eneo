<script lang="ts">
  import * as Command from "$lib/components/ui/command/index.js";

  type Props = { placeholder?: string };

  let { placeholder }: Props = $props();
</script>

<Command.Input data-slot="model-selector-input" {placeholder} />
