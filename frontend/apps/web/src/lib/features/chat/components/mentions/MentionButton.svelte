<script lang="ts">
  import { Button, Tooltip } from "@intric/ui";
  import { getMentionInput } from "./MentionInput";
  import { IconAtSymbol } from "@intric/icons/at-symbol";

  const {
    showMentionPicker,
    states: { mentions }
  } = getMentionInput();

  let mentionsDiabled = $derived($mentions.length > 0);
  import { m } from "$lib/paraglide/messages";
</script>

<Tooltip text={mentionsDiabled ? m.one_mention_per_question() : undefined}>
  <Button
    unstyled
    disabled={mentionsDiabled}
    class="bg-secondary text-primary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center gap-1 rounded-lg pr-2 pl-1"
    on:click={showMentionPicker}
  >
    <IconAtSymbol></IconAtSymbol>
    {m.mention()}</Button
  >
</Tooltip>
