<!-- Appearance fields with the contrast check, shared by widget and template editors. -->
<script lang="ts">
  import type { WidgetTheme } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { contrastVerdict, DEFAULT_PRIMARY_COLOR, isHexColor } from "./contrast";
  import { inputClass } from "./fieldStyles";

  type Props = {
    theme: WidgetTheme;
    onChange: (change: Partial<WidgetTheme>) => void;
  };

  let { theme, onChange }: Props = $props();

  function number(event: Event, apply: (value: number) => void) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (Number.isFinite(value)) apply(value);
  }

  const primaryColor = $derived(theme.primary_color ?? DEFAULT_PRIMARY_COLOR);
  const contrast = $derived(contrastVerdict(primaryColor));
  const contrastLabel = $derived.by(() => {
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
</script>

<Settings.Row
  title={m.widget_admin_primary_color()}
  description={m.widget_admin_primary_color_description()}
  let:aria
>
  <div class="flex items-center gap-3">
    <input
      type="color"
      class="border-default h-10 w-14 cursor-pointer rounded-lg border"
      aria-label={m.widget_admin_primary_color_picker()}
      value={isHexColor(primaryColor) ? primaryColor : DEFAULT_PRIMARY_COLOR}
      oninput={(event) => onChange({ primary_color: event.currentTarget.value })}
    />
    <input
      type="text"
      class={inputClass}
      pattern="#[0-9a-fA-F]{6}"
      maxlength="7"
      aria-invalid={contrast.verdict === "invalid"}
      {...aria}
      value={primaryColor}
      oninput={(event) => onChange({ primary_color: event.currentTarget.value.trim() })}
    />
  </div>
  <p
    class={[
      "mt-2 text-sm",
      contrast.verdict === "text" ? "text-positive-default" : "text-warning-stronger"
    ]}
    aria-live="polite"
  >
    {contrastLabel}
  </p>
</Settings.Row>
<Settings.Row
  title={m.widget_admin_color_scheme()}
  description={m.widget_admin_color_scheme_description()}
  let:aria
>
  <select
    class={inputClass}
    {...aria}
    value={theme.color_scheme ?? "auto"}
    onchange={(event) =>
      onChange({ color_scheme: event.currentTarget.value as WidgetTheme["color_scheme"] })}
  >
    <option value="auto">{m.widget_admin_scheme_auto()}</option>
    <option value="light">{m.widget_admin_scheme_light()}</option>
    <option value="dark">{m.widget_admin_scheme_dark()}</option>
  </select>
</Settings.Row>
<Settings.Row
  title={m.widget_admin_position()}
  description={m.widget_admin_position_description()}
  let:aria
>
  <select
    class={inputClass}
    {...aria}
    value={theme.position ?? "bottom-right"}
    onchange={(event) =>
      onChange({ position: event.currentTarget.value as WidgetTheme["position"] })}
  >
    <option value="bottom-right">{m.widget_admin_position_right()}</option>
    <option value="bottom-left">{m.widget_admin_position_left()}</option>
  </select>
</Settings.Row>
<Settings.Row
  title={m.widget_admin_radius()}
  description={m.widget_admin_radius_description()}
  let:aria
>
  <input
    type="number"
    class={inputClass}
    min="0"
    max="24"
    step="1"
    {...aria}
    value={theme.radius ?? 12}
    oninput={(event) =>
      number(event, (value) => onChange({ radius: Math.min(24, Math.max(0, value)) }))}
  />
</Settings.Row>
