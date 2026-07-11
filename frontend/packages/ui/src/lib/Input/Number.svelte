<script lang="ts">
  import { uid } from "uid";
  const id = uid(8);

  let cls = "";
  export { cls as class };
  export let labelClass = "";
  export let inputClass = "";
  export let value: number;
  export let step = 1;
  export let max = 100;
  export let min = 0;
  export let hiddenLabel: boolean = false;

  function validate() {
    if (value > max) {
      value = max;
    } else if (value < min) {
      value = min;
    }
  }
</script>

<div class="flex flex-col gap-1 {cls}">
  <label for={id} class="pl-3 font-medium {labelClass}" class:sr-only={hiddenLabel}><slot /></label>
  <input
    bind:value
    type="number"
    {id}
    {...$$restProps}
    {step}
    {max}
    {min}
    on:input={validate}
    class="border-stronger bg-primary ring-default placeholder:text-placeholder h-10 items-center
  justify-between overflow-hidden rounded-lg border px-3 py-2 text-center shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 {inputClass}"
  />
</div>

<style>
  input[type="number"]::-webkit-inner-spin-button,
  input[type="number"]::-webkit-outer-spin-button {
    opacity: 1;
  }
</style>
