<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { getMentionInput } from "./MentionInput";
  import { AtSign } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    showMentionPicker,
    states: { mentions }
  } = getMentionInput();

  const mentionsDisabled = $derived($mentions.length > 0);
</script>

<Button
  variant="ghost"
  size="sm"
  type="button"
  disabled={mentionsDisabled}
  onclick={showMentionPicker}
  class="h-9 shrink-0 gap-1 rounded-lg px-2 @[44rem]/composer:gap-1.5 @[44rem]/composer:px-3"
  aria-label={mentionsDisabled ? m.one_mention_per_question() : m.mention()}
  title={mentionsDisabled ? m.one_mention_per_question() : m.mention()}
>
  <AtSign class="size-4" />
  <span class="hidden @[44rem]/composer:inline">{m.mention()}</span>
</Button>
