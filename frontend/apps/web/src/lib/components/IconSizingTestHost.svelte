<script lang="ts">
  import { IconCopy } from "@eneo/icons/copy";
  import { Button } from "$lib/components/ui/button/index.js";
</script>

<span data-testid="plain"><IconCopy /></span>
<span data-testid="sized"><IconCopy class="size-4" /></span>
<Button size="icon" data-testid="icon-button"><IconCopy /></Button>
<Button size="sm" data-testid="small-button"><IconCopy /></Button>
