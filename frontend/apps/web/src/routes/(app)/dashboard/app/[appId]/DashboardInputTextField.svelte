<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  export let description: string | null | undefined;
  export let value: string | null;
  let text: string = value ?? "";
</script>

<div class="flex w-full flex-col">
  <textarea
    aria-label={m.enter_your_question_here()}
    bind:value={text}
    on:input={() => {
      if (text) {
        value = text;
      } else {
        value = null;
      }
    }}
    name="textinput"
    placeholder={description ?? m.enter_text_here()}
    rows="5"
    class="border-default bg-primary placeholder:text-secondary w-full resize-none rounded-xl border px-4 py-3 text-base"
  ></textarea>
</div>
