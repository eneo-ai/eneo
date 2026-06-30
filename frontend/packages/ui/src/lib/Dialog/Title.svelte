<script lang="ts">
  import { IconXMark } from "@eneo/icons/x-mark";
  import { Button } from "../Button/index.js";
  import { getDialog } from "./ctx.js";

  const {
    elements: { title, close }
  } = getDialog();
</script>

<div class="flex items-center justify-between pb-2">
  <h2 {...$title} use:title class="truncate text-xl font-medium">
    <slot />
  </h2>
  <Button is={[$close]} label="close" class="-mr-2" padding="icon">
    <IconXMark />
  </Button>
</div>
