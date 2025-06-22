<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  
  export let description: string | null | undefined;
  export let value: string | null;
  let text: string;
  let textarea: HTMLTextAreaElement;

  function calculateTextAreaHeight() {
    textarea.style.height = "";
    const scrollHeight = Math.min(textarea.scrollHeight, 250);
    textarea.style.height = scrollHeight > 45 ? scrollHeight + "px" : "auto";
    textarea.style.overflowY = scrollHeight === 250 ? "auto" : "hidden";
  }
</script>

<div
  class="border-stronger bg-secondary flex max-h-[40vh] max-w-[80ch] min-w-[50ch] flex-col justify-center rounded-[1.2rem] border p-0.5 shadow-xl"
>
  <textarea
    aria-label={m.enter_your_question_here()}
    bind:this={textarea}
    bind:value={text}
    on:input={() => {
      calculateTextAreaHeight();
      if (text) {
        value = text;
      } else {
        value = null;
      }
    }}
    name="textinput"
    placeholder={description ?? m.enter_text_here()}
    rows="4"
    class="border-default bg-primary placeholder:text-secondary flex-grow resize-none overflow-y-auto rounded-[1rem] border px-6 py-3 text-lg"
  ></textarea>
</div>
