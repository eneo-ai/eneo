<script lang="ts">
  import { createSwitch } from "@melt-ui/svelte";
  import { writable } from "svelte/store";
  import { uid } from "uid";

  let cls = "";
  export { cls as class };
  export let value = false;
  export let disabled = false;
  export let sideEffect: ((params: { current: boolean; next: boolean }) => void) | undefined =
    undefined;

  const checked = writable(value);

  const {
    elements: { root, input },
    options
  } = createSwitch({
    checked,
    onCheckedChange({ curr, next }) {
      sideEffect?.({ current: curr, next });
      value = next;
      return next;
    },
    disabled
  });

  const label_id = uid(8);
  const id = uid(8);
  const check_id = uid(8);

  $: checked.set(value);
  $: options.disabled.set(disabled);
</script>

<fieldset class="flex items-center gap-4 {cls}">
  <label class="flex-grow" for={id} id={label_id}>
    <slot />
  </label>
  <button
    {...$root}
    use:root
    class="bg-tertiary data-[state=checked]:bg-accent-default relative h-6 cursor-pointer rounded-full transition-colors disabled:cursor-not-allowed"
    {id}
    aria-labelledby={label_id}
  >
    <span class="thumb block rounded-full bg-[var(--text-on-fill)] transition"></span>
  </button>
  <input {...$input} use:input id={check_id} />
</fieldset>

<style>
  button {
    --w: 2.75rem;
    --padding: 0.15rem;
    width: var(--w);
    min-width: var(--w);
    box-shadow: 0 0 0 1px var(--border-stronger);
  }

  .thumb {
    --size: 1.25rem;
    width: var(--size);
    height: var(--size);
    transform: translateX(var(--padding));
  }

  :global([data-state="checked"]) .thumb {
    transform: translateX(calc(var(--w) - var(--size) - var(--padding)));
  }
</style>
