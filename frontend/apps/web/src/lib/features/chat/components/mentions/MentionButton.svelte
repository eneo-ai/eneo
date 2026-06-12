<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { getMentionInput } from "./MentionInput";
  import { AtSign } from "lucide-svelte";
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
  class="h-9 gap-1.5 rounded-lg"
  title={mentionsDisabled ? m.one_mention_per_question() : m.mention()}
>
  <AtSign class="size-4" />
  <span class="hidden sm:inline">{m.mention()}</span>
</Button>
