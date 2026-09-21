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
  import {
    contrastRatio,
    contrastVerdict,
    DARK_SURFACE,
    DEFAULT_PRIMARY_COLOR,
    isHexColor,
    LIGHT_SURFACE,
    normalizeHexColor,
    readableOn
  } from "../contrast";

  type Props = {
    id: string;
    label: string;
    description: string;
    value: string | null;
    onChange: (value: string | null) => void;
    /** Optional colours can be cleared back to the neutral surface. */
    clearable?: boolean;
    /** Show how the colour fares against the surface it will sit on. */
    checkContrast?: boolean;
    /**
     * Warn when neither white nor near-black text reaches 4.5:1 on the colour
     * (mid-tone colours); the panel derives its text colour from it.
     */
    checkTextOn?: boolean;
    /** The surface behind the colour: the white page or the dark panel. */
    surface?: "light" | "dark";
    /** Read-only, e.g. when a template governs the appearance. */
    disabled?: boolean;
    /** Extra ids for aria-describedby, e.g. the template lock hint. */
    describedBy?: string;
  };

  let {
    id,
    label,
    description,
    value,
    onChange,
    clearable = false,
    checkContrast = false,
    checkTextOn = checkContrast,
    surface = "light",
    disabled = false,
    describedBy = ""
  }: Props = $props();

  // What is typed stays local until it is a complete hex colour; the server
  // only ever sees valid #RRGGBB values, so no error appears mid-typing.
  let draft = $state(untrack(() => value ?? ""));
  let lastSaved = untrack(() => value ?? "");
  $effect(() => {
    const saved = value ?? "";
    if (saved !== lastSaved) {
      lastSaved = saved;
      // The echo of what was just typed must not replace the draft: a
      // six-digit colour passes through a valid three-digit prefix.
      if (!isHexColor(draft) || normalizeHexColor(draft) !== saved) draft = saved;
    }
  });
  const current = $derived(draft);
  const pickerValue = $derived(
    isHexColor(current) ? normalizeHexColor(current) : DEFAULT_PRIMARY_COLOR
  );
  const contrast = $derived(
    checkContrast && current
      ? contrastVerdict(current, surface === "dark" ? DARK_SURFACE : LIGHT_SURFACE)
      : null
  );

  function typed(raw: string) {
    draft = raw.trim();
    if (draft === "" && clearable) onChange(null);
    else if (isHexColor(draft)) onChange(normalizeHexColor(draft));
  }

  function settle() {
    if (isHexColor(draft)) draft = normalizeHexColor(draft);
  }
  const contrastLabel = $derived.by(() => {
    if (!contrast) return "";
    const ratio = contrast.ratio.toFixed(1);
    const dark = surface === "dark";
    switch (contrast.verdict) {
      case "text":
        return dark
          ? m.widget_admin_contrast_dark_ok({ ratio })
          : m.widget_admin_contrast_ok({ ratio });
      case "graphics":
        return dark
          ? m.widget_admin_contrast_dark_graphics_only({ ratio })
          : m.widget_admin_contrast_graphics_only({ ratio });
      case "fail":
        return dark
          ? m.widget_admin_contrast_dark_fail({ ratio })
          : m.widget_admin_contrast_fail({ ratio });
      default:
        return m.widget_admin_contrast_invalid();
    }
  });
  const invalid = $derived(current !== "" && !isHexColor(current));
  // The panel paints text in whatever reads best on the colour; for mid-tone
  // colours that is still below the 4.5:1 the visitor's messages need.
  const textOnRatio = $derived(
    checkTextOn && isHexColor(current) ? contrastRatio(readableOn(current), current) : null
  );
  const textOnWarning = $derived(
    textOnRatio !== null && textOnRatio < 4.5
      ? m.widget_admin_contrast_text_on_fail({ ratio: textOnRatio.toFixed(1) })
      : ""
  );
  const describedByIds = $derived(
    [`${id}-description`, invalid ? `${id}-error` : "", describedBy].filter(Boolean).join(" ")
  );
</script>

<Field.Field data-invalid={invalid || undefined}>
  <Field.Label for={id}>{label}</Field.Label>
  <div class="flex items-center gap-2">
    <span class="relative h-8 w-12 shrink-0">
      {#if clearable && !current}
        <!-- No colour chosen: an empty, dashed swatch instead of a misleading default. -->
        <span
          class="border-default absolute inset-0 rounded-lg border border-dashed"
          aria-hidden="true"
        ></span>
      {/if}
      <input
        type="color"
        class={[
          "border-default h-8 w-12 cursor-pointer rounded-lg border bg-transparent p-0.5",
          clearable && !current && "opacity-0"
        ]}
        aria-label={`${label}: ${m.widget_admin_primary_color_picker()}`}
        value={pickerValue}
        {disabled}
        oninput={(event) => typed(event.currentTarget.value)}
      />
    </span>
    <Input
      {id}
      class="max-w-40 font-mono"
      maxlength={7}
      {disabled}
      placeholder={clearable ? m.widget_admin_header_color_none() : DEFAULT_PRIMARY_COLOR}
      aria-invalid={invalid}
      aria-describedby={describedByIds}
      value={current}
      oninput={(event) => typed(event.currentTarget.value)}
      onblur={settle}
    />
    {#if clearable && current && !disabled}
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
    <Field.Error id={`${id}-error`}>{m.widget_admin_contrast_invalid()}</Field.Error>
  {/if}
  {#if textOnWarning}
    <p class="text-warning-stronger text-sm" aria-live="polite">{textOnWarning}</p>
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
