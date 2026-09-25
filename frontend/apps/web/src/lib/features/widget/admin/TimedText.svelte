<!--
  A translated sentence with a date in it, where the date is a <time> element
  that carries the machine-readable value.
-->
<script lang="ts">
  import { formatDateMedium } from "$lib/core/formatting/dateTime";

  type Props = {
    /** The sentence, given the formatted date to put in its `{date}` slot. */
    message: (date: string) => string;
    /** An ISO date or date-time. */
    value: string;
    format?: (value: string) => string;
  };

  let { message, value, format = formatDateMedium }: Props = $props();

  // A private-use character no translation contains marks where the date goes.
  const SLOT = "\uE000";
  const parts = $derived(message(SLOT).split(SLOT));
</script>

{#if parts.length === 2}{parts[0]}<time datetime={value}>{format(value)}</time
  >{parts[1]}{:else}{message(format(value))}{/if}
