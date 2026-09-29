<script lang="ts">
  import { IconDownload } from "@eneo/icons/download";
  import { IconPrint } from "@eneo/icons/print";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { downloadTextFile } from "$lib/core/helpers/download";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils";

  type Props = {
    type: "output" | "transcription";
    text: string;
    /** Suggested name when saving `text` as a file. */
    fileName: string;
    /**
     * Printed by the print button (nothing while it is missing). It needs the
     * `printable-document` class: in print mode app.css hides everything else.
     */
    printElement: HTMLElement | undefined;
    /** A bordered column of ghost buttons with tooltips on the left, instead of a row of outlined buttons. */
    floating?: boolean;
    class?: string;
  };

  let { type, text, fileName, printElement, floating = false, class: className }: Props = $props();

  const typeLabel = $derived(
    (type === "output" ? m.output() : m.transcription()).toLocaleLowerCase()
  );

  const variant = $derived(floating ? "ghost" : "outline");
  const tooltipSide = $derived(floating ? "left" : "bottom");

  function print() {
    if (!printElement) return;
    const printNode = printElement.cloneNode(true);
    document.body.appendChild(printNode);
    document.body.classList.add("print-mode");
    window.print();
    document.body.classList.remove("print-mode");
    document.body.removeChild(printNode);
  }

  function download() {
    if (!text) {
      toast.warning(m.not_output_to_save());
      return;
    }
    return downloadTextFile(text, fileName);
  }
</script>

<div
  class={cn(
    "flex gap-1",
    floating && "border-default bg-primary flex-col rounded-lg border p-1 shadow",
    className
  )}
>
  {#if printElement}
    <Tooltip.Root>
      <Tooltip.Trigger onclick={print}>
        {#snippet child({ props })}
          <Button
            {...props}
            {variant}
            size="icon"
            aria-label={m.print_save_type_pdf({ type: typeLabel })}
          >
            <IconPrint size="md" />
          </Button>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content side={tooltipSide}
        >{m.print_save_type_pdf({ type: typeLabel })}</Tooltip.Content
      >
    </Tooltip.Root>
  {/if}

  <Tooltip.Root>
    <Tooltip.Trigger onclick={download}>
      {#snippet child({ props })}
        <Button
          {...props}
          {variant}
          size="icon"
          aria-label={m.download_type_raw_text({ type: typeLabel })}
        >
          <IconDownload />
        </Button>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content side={tooltipSide}
      >{m.download_type_raw_text({ type: typeLabel })}</Tooltip.Content
    >
  </Tooltip.Root>

  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <CopyButton
          {...props}
          {text}
          {variant}
          disabled={!text}
          label={m.copy_type({ type: typeLabel })}
        />
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content side={tooltipSide}>{m.copy_type({ type: typeLabel })}</Tooltip.Content>
  </Tooltip.Root>
</div>
