<script lang="ts">
  import { RotateCcw } from "@lucide/svelte";
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { useId } from "bits-ui";
  import { getContext } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import { settingsDensityContext, type SettingsDensity } from "./density";

  export let title: string;
  export let description: string = "";
  /** Deeper explanation behind a (?) icon: meaning, range, default, effect. */
  export let help: string = "";
  export let fullWidth = false;
  export let density: SettingsDensity =
    getContext<SettingsDensity>(settingsDensityContext) ?? "default";

  export let hasChanges = false;
  export let revertFn: (() => void) | undefined = undefined;

  const labelId = useId();
  const descriptionId = useId();

  $: inputSectionClass = cn(
    "flex w-full flex-col",
    density === "compact" ? "pt-1 xl:pt-3" : "pt-3",
    !fullWidth && (density === "compact" ? "xl:w-[56%]" : "lg:w-[56%]")
  );

  $: descriptionSectionClass = cn(
    "flex w-full flex-col justify-between sm:flex-row",
    !fullWidth && (density === "compact" ? "xl:w-[40%]" : "lg:w-[40%]")
  );
</script>

<div
  class:!flex-col={fullWidth}
  class:gap-y-2={fullWidth}
  class="flex flex-col justify-between gap-y-3 px-4"
  class:lg:flex-row={density === "default"}
  class:lg:pr-6={density === "default"}
  class:lg:pl-0.5={density === "default"}
  class:xl:flex-row={density === "compact"}
  class:xl:pr-6={density === "compact"}
  class:xl:pl-0.5={density === "compact"}
  data-row-has-changes={hasChanges}
>
  <div class={descriptionSectionClass}>
    <div
      class="flex flex-col pl-2"
      class:pr-12={density === "default"}
      class:xl:pr-12={density === "compact"}
      class:gap-1.5={density === "default"}
      class:gap-1={density === "compact"}
    >
      <h3
        class="text-primary flex items-center tracking-tight"
        class:text-base={density === "default"}
        class:font-semibold={density === "default"}
        class:text-sm={density === "compact"}
        class:font-medium={density === "compact"}
        id={labelId}
      >
        <span
          class={cn(
            "transition-all duration-300",
            hasChanges
              ? "mr-2 h-2 w-2 rounded-full bg-[var(--change-indicator)]"
              : "h-0 w-0 bg-transparent"
          )}
        ></span>{title}<slot name="title"></slot>
        {#if help}
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger
                aria-label={help}
                class="ml-1.5 inline-flex items-center align-middle"
              >
                <IconQuestionMark class="text-muted hover:text-primary size-4" aria-hidden="true" />
              </Tooltip.Trigger>
              <Tooltip.Content class="max-w-[320px]">{help}</Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        {/if}
        {#if revertFn}
          <button
            type="button"
            class="border-default hover:bg-hover-dimmer ml-2 inline-flex -translate-y-[1px] items-center gap-1.5 self-end rounded-lg border px-2 py-0.5 text-sm font-normal transition-all hover:shadow disabled:opacity-0"
            disabled={!hasChanges}
            aria-label="{m.discard_changes()}: {title}"
            on:click={revertFn}
          >
            <RotateCcw class="size-3.5" aria-hidden="true" />
            {m.discard_changes()}
          </button>
        {/if}
      </h3>
      {#if description}
        <p
          class="text-secondary leading-relaxed"
          class:text-[0.875rem]={density === "default"}
          class:text-[0.8125rem]={density === "compact"}
          id={descriptionId}
        >
          {description}
        </p>
      {/if}
      <slot name="description" />
    </div>
    {#if $$slots.toolbar}
      <div class="p-4 pr-3">
        <slot name="toolbar" />
      </div>
    {/if}
  </div>

  <div class={inputSectionClass}>
    <slot
      {labelId}
      {descriptionId}
      aria={{ "aria-labelledby": labelId, "aria-describedby": descriptionId }}
    />
  </div>
</div>
