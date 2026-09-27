<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  type Props = {
    description?: string | null;
    /** `null` while the field is empty. */
    value: string | null;
    /** A plain full-width textarea instead of the framed one that grows with its content. */
    compact?: boolean;
  };

  let { description, value = $bindable(), compact = false }: Props = $props();

  function growToContent(textarea: HTMLTextAreaElement) {
    textarea.style.height = "";
    const scrollHeight = Math.min(textarea.scrollHeight, 250);
    textarea.style.height = scrollHeight > 45 ? scrollHeight + "px" : "auto";
    textarea.style.overflowY = scrollHeight === 250 ? "auto" : "hidden";
  }
</script>

<div
  class={compact
    ? "flex w-full flex-col"
    : "border-stronger bg-secondary flex max-h-[40vh] max-w-[80ch] min-w-[50ch] flex-col justify-center rounded-[1.2rem] border p-0.5 shadow-xl"}
>
  <textarea
    aria-label={m.enter_your_question_here()}
    bind:value={() => value ?? "", (text) => (value = text || null)}
    oninput={(event) => {
      if (!compact) growToContent(event.currentTarget);
    }}
    name="textinput"
    placeholder={description ?? m.enter_text_here()}
    rows={compact ? 5 : 4}
    class={compact
      ? "border-default bg-primary placeholder:text-secondary w-full resize-none rounded-xl border px-4 py-3 text-base"
      : "border-default bg-primary placeholder:text-secondary flex-grow resize-none overflow-y-auto rounded-[1rem] border px-6 py-3 text-lg"}
  ></textarea>
</div>
