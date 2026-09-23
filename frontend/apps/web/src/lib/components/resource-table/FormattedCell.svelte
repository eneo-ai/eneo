<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { cn } from "$lib/utils.js";

  type Props = {
    value: string | number;
    align?: "start" | "end" | "center";
    monospaced?: boolean;
    italic?: boolean;
    bold?: boolean;
    truncate?: boolean;
    class?: string;
  };

  let {
    value,
    align = "start",
    monospaced = false,
    italic = false,
    bold = false,
    truncate = false,
    class: className
  }: Props = $props();
</script>

<div
  class={cn(
    "flex w-full items-center",
    monospaced && "font-mono",
    bold && "font-semibold",
    italic && "italic",
    truncate && "line-clamp-1 truncate",
    className
  )}
  style="justify-content: flex-{align}"
>
  {value}
</div>
