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
  export let hiddenLabel: boolean = false;
</script>

<div class="flex flex-col gap-1 {containerClass}">
  <label for={id} class="pl-3 font-medium {labelClass}" class:sr-only={hiddenLabel}>
    {#if $$slots.default}
      <slot />
    {:else}
      <div class="text-primary flex items-baseline justify-between">
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
  <input
    bind:this={inputElement}
    bind:value
    type="text"
    on:input={() => {
      isValid = inputElement?.validity.valid ?? false;
    }}
    {id}
    {...$$restProps}
    {required}
    aria-required={required}
    aria-describedby={description ? `${id}-description` : undefined}
    aria-invalid={!isValid}
    class="border-stronger bg-primary text-primary ring-default placeholder:text-muted h-10
  items-center justify-between overflow-hidden rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 {inputClass}"
  />
</div>
