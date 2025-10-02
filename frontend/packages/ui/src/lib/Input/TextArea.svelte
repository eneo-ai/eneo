<script lang="ts">
  import { uid } from "uid";
  import { getUIMessage } from "$lib/utils/messages.js";
  const id = uid(8);

  let containerClass = "";

  export { containerClass as class };
  export let label = "";
  export let description: string | undefined = undefined;
  export let value: string;
  export let rows = 4;
  export let required = false;
</script>

<div class="flex flex-col gap-1 {containerClass}">
  <label for={id} class="text-primary pl-3 font-medium">
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
  <textarea
    {id}
    {rows}
    {required}
    aria-required={required}
    on:change
    bind:value
    {...$$restProps}
    class="border-stronger bg-primary text-primary ring-default placeholder:text-muted h-full min-h-10 items-center justify-between rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
  ></textarea>
</div>
