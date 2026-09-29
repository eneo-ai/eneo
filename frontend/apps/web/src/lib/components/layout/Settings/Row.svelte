<script lang="ts">
  import { useId } from "bits-ui";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  export let title: string;
  export let description: string;
  export let fullWidth = false;

  export let hasChanges = false;
  export let revertFn: (() => void) | undefined = undefined;

  const labelId = useId();
  const descriptionId = useId();
</script>

<div
  class:!flex-col={fullWidth}
  class:gap-y-2={fullWidth}
  class="flex flex-col justify-between gap-y-4 px-4 lg:flex-row lg:pr-6 lg:pl-0.5"
  data-row-has-changes={hasChanges}
>
  <div class={cn("flex w-full justify-between", !fullWidth && "lg:w-[40%]")}>
    <div class="flex flex-col gap-2 pr-12 pl-2">
      <h3 class="flex items-center text-lg font-medium" id={labelId}>
        <span
          class={cn(
            "transition-all duration-300",
            hasChanges
              ? "mr-2 h-2 w-2 rounded-full bg-[var(--change-indicator)]"
              : "h-0 w-0 bg-transparent"
          )}
        ></span>{title}<slot name="title"></slot>
        {#if revertFn}
          <button
            type="button"
            class="border-default hover:bg-hover-dimmer ml-2 -translate-y-[1px] self-end rounded-lg border px-2 py-0.5 text-sm font-normal transition-all hover:shadow disabled:opacity-0"
            disabled={!hasChanges}
            on:click={revertFn}>{m.discard_changes()}</button
          >
        {/if}
      </h3>
      <p class="text-secondary whitespace-pre-wrap" id={descriptionId}>
        {description}
      </p>
      <slot name="description" />
    </div>
    <div class="p-4 pr-3">
      <slot name="toolbar" />
    </div>
  </div>

  <div class={cn("flex w-full flex-col pt-3", !fullWidth && "lg:w-[56%]")}>
    <slot
      {labelId}
      {descriptionId}
      aria={{ "aria-labelledby": labelId, "aria-describedby": descriptionId }}
    />
  </div>
</div>
