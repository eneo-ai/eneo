<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { dialogLayout, type DialogWidth } from "$lib/components/dialogLayout.js";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    open?: boolean;
    title: string;
    description?: string;
    label: string;
    /**
     * The field's value each time the dialog opens: the current name when renaming, empty when
     * creating. Submit stays disabled while the trimmed value is empty or equal to it.
     */
    initial?: string;
    placeholder?: string;
    submitLabel: string;
    /** Shown on the submit button while `onSubmit` runs. */
    pendingLabel?: string;
    width?: DialogWidth;
    /** Prefix for the error toast; a function receives the submitted name. */
    errorContext?: string | ((name: string) => string);
    /**
     * Receives the trimmed name. The dialog closes when this resolves; when it throws, it stays
     * open and toasts the error.
     */
    onSubmit: (name: string) => unknown;
    /** Renders the element that opens the dialog; spread `props` onto it. */
    trigger?: Snippet<[{ props: Record<string, unknown> }]>;
    /** Extra control at the start of the footer, e.g. a switch. */
    footerExtra?: Snippet;
  };

  let {
    open = $bindable(false),
    title,
    description,
    label,
    initial = "",
    placeholder,
    submitLabel,
    pendingLabel,
    width = "small",
    errorContext,
    onSubmit,
    trigger,
    footerExtra
  }: Props = $props();

  const id = $props.id();
  let draft = $state("");
  let pending = $state(false);

  const name = $derived(draft.trim());
  const canSubmit = $derived(name !== "" && name !== initial.trim());

  $effect(() => {
    if (open) draft = untrack(() => initial);
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (pending || !canSubmit) return;
    const submitted = name;
    pending = true;
    try {
      await onSubmit(submitted);
      open = false;
    } catch (error) {
      toastError(
        error,
        typeof errorContext === "function" ? errorContext(submitted) : errorContext
      );
    } finally {
      pending = false;
    }
  }
</script>

<Dialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!pending) open = value;
    }
  }
>
  {#if trigger}
    <Dialog.Trigger>
      {#snippet child({ props })}
        {@render trigger({ props })}
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content class={dialogLayout.content(width)} closeLabel={m.close()}>
    <form class="contents" onsubmit={submit}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{title}</Dialog.Title>
        {#if description}
          <Dialog.Description>{description}</Dialog.Description>
        {/if}
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="px-4 py-4">
            <Field.Label for="{id}-name">
              {label}
              <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
            </Field.Label>
            <Input id="{id}-name" bind:value={draft} {placeholder} required />
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        {#if footerExtra}
          <div class="sm:mr-auto">{@render footerExtra()}</div>
        {/if}
        <Dialog.Close class={buttonVariants({ variant: "outline" })} disabled={pending}>
          {m.cancel()}
        </Dialog.Close>
        <Button
          type="submit"
          disabled={!canSubmit}
          aria-disabled={pending}
          aria-busy={pending}
          class={pending ? "pointer-events-none opacity-50" : undefined}
        >
          {pending && pendingLabel ? pendingLabel : submitLabel}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
