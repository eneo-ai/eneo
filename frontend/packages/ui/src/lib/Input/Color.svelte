<script lang="ts">
  import { uid } from "uid";
  import { getUIMessage } from "$lib/utils/messages.js";
  const id = uid(8);

  let containerClass = "";
  let inputElement: HTMLInputElement;

  export { containerClass as class };
  export let inputClass = "";
  export let labelClass = "";
  export let label = "";
  export let description: string | undefined = undefined;
  export let value: string;
  export let isValid: boolean = false;
  export let required: boolean = false;
</script>

<div class="flex flex-col gap-1 {containerClass}">
  <label for={id} class="text-primary pl-3 font-medium {labelClass}">
    {#if $$slots.default}
      <slot />
    {:else}
      <div class="flex items-baseline justify-between">
        <div>
          {label}
          {#if required}
            <span class="text-muted px-2 text-[0.9rem] font-normal" aria-hidden="true"
              >({getUIMessage("required")})</span
            >
          {/if}
        </div>
        {#if description}
          <span class="text-muted px-2 text-[0.9rem] font-normal">{description}</span>
        {/if}
      </div>
    {/if}
  </label>
  <div class="flex justify-between">
    <input
      bind:this={inputElement}
      type="text"
      {id}
      {...$$restProps}
      {required}
      on:input={() => {
        isValid = inputElement?.validity.valid ?? false;
      }}
      aria-required={required}
      bind:value
      class="ult border-stronger bg-primary ring-default placeholder:text-muted
      mr-4 h-10 w-full items-center overflow-hidden rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 {inputClass}"
    />
    <input
      type="color"
      bind:value
      class="border-stronger bg-primary h-10 min-h-10 w-10 min-w-10 rounded-lg border px-1 py-0.5"
    />
  </div>
</div>
