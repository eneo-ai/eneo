<!--
  A colour: native picker plus the hex value, with an optional WCAG contrast
  verdict against white and a way to clear optional colours.
-->
<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { contrastVerdict, DEFAULT_PRIMARY_COLOR, isHexColor } from "../contrast";

  type Props = {
    id: string;
    label: string;
    description: string;
    value: string | null;
    onChange: (value: string | null) => void;
    /** Optional colours can be cleared back to the neutral surface. */
    clearable?: boolean;
    /** Show how the colour fares against white text and icons. */
    checkContrast?: boolean;
  };

  let {
    id,
    label,
    description,
    value,
    onChange,
    clearable = false,
    checkContrast = false
  }: Props = $props();

  // What is typed stays local until it is a complete hex colour; the server
  // only ever sees valid values, so no error appears mid-typing.
  let draft = $state(untrack(() => value ?? ""));
  $effect(() => {
    if ((value ?? "") !== draft && (isHexColor(draft) || draft === "")) draft = value ?? "";
  });
  const current = $derived(draft);
  const pickerValue = $derived(isHexColor(current) ? current : DEFAULT_PRIMARY_COLOR);
  const contrast = $derived(checkContrast && current ? contrastVerdict(current) : null);

  function typed(raw: string) {
    draft = raw.trim();
    if (draft === "" && clearable) onChange(null);
    else if (isHexColor(draft)) onChange(draft.toUpperCase());
  }
  const contrastLabel = $derived.by(() => {
    if (!contrast) return "";
    const ratio = contrast.ratio.toFixed(1);
    switch (contrast.verdict) {
      case "text":
        return m.widget_admin_contrast_ok({ ratio });
      case "graphics":
        return m.widget_admin_contrast_graphics_only({ ratio });
      case "fail":
        return m.widget_admin_contrast_fail({ ratio });
      default:
        return m.widget_admin_contrast_invalid();
    }
  });
  const invalid = $derived(current !== "" && !isHexColor(current));
</script>

<Field.Field data-invalid={invalid || undefined}>
  <Field.Label for={id}>{label}</Field.Label>
  <div class="flex items-center gap-2">
    <input
      type="color"
      class="border-default h-8 w-12 shrink-0 cursor-pointer rounded-lg border bg-transparent p-0.5"
      aria-label={m.widget_admin_primary_color_picker()}
      value={pickerValue}
      oninput={(event) => typed(event.currentTarget.value)}
    />
    <Input
      {id}
      class="max-w-40 font-mono uppercase"
      maxlength={7}
      placeholder={clearable ? m.widget_admin_header_color_none() : DEFAULT_PRIMARY_COLOR}
      aria-invalid={invalid}
      aria-describedby={`${id}-description`}
      value={current}
      oninput={(event) => typed(event.currentTarget.value)}
    />
    {#if clearable && current}
      <Button
        variant="ghost"
        size="sm"
        onclick={() => {
          draft = "";
          onChange(null);
        }}
      >
        {m.widget_admin_color_reset()}
      </Button>
    {/if}
  </div>
  <Field.Description id={`${id}-description`}>{description}</Field.Description>
  {#if invalid}
    <Field.Error>{m.widget_admin_contrast_invalid()}</Field.Error>
  {/if}
  {#if contrastLabel}
    <p
      class={[
        "text-sm",
        contrast?.verdict === "text" ? "text-positive-default" : "text-warning-stronger"
      ]}
      aria-live="polite"
    >
      {contrastLabel}
    </p>
  {/if}
</Field.Field>
