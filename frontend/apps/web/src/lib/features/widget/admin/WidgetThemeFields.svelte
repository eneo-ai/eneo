<!-- Appearance: colours, logo, shape and placement of the launcher. -->
<script lang="ts">
  import type { WidgetTheme } from "@eneo/eneo-js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import ColorField from "./ColorField.svelte";

  type Props = {
    theme: WidgetTheme;
    onChange: (change: Partial<WidgetTheme>) => void;
    idPrefix?: string;
  };

  let { theme, onChange, idPrefix = "widget" }: Props = $props();

  const id = (name: string) => `${idPrefix}-${name}`;

  const schemeLabels = $derived({
    auto: m.widget_admin_scheme_auto(),
    light: m.widget_admin_scheme_light(),
    dark: m.widget_admin_scheme_dark()
  });
  const positionLabels = $derived({
    "bottom-right": m.widget_admin_position_right(),
    "bottom-left": m.widget_admin_position_left()
  });

  function number(event: Event, apply: (value: number) => void) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (Number.isFinite(value)) apply(value);
  }
</script>

<Field.Group class="grid gap-6">
  <ColorField
    id={id("primary-color")}
    label={m.widget_admin_primary_color()}
    description={m.widget_admin_primary_color_description()}
    value={theme.primary_color ?? null}
    checkContrast
    onChange={(value) => onChange({ primary_color: value ?? "" })}
  />

  <ColorField
    id={id("header-color")}
    label={m.widget_admin_header_color()}
    description={m.widget_admin_header_color_description()}
    value={theme.header_color ?? null}
    clearable
    onChange={(value) => onChange({ header_color: value })}
  />

  <Field.Field>
    <Field.Label for={id("logo-url")}>{m.widget_admin_logo_url()}</Field.Label>
    <div class="flex items-center gap-3">
      <Input
        id={id("logo-url")}
        type="url"
        maxlength={500}
        value={theme.logo_url ?? ""}
        aria-describedby={id("logo-url-help")}
        oninput={(event) => onChange({ logo_url: event.currentTarget.value.trim() || null })}
      />
      {#if theme.logo_url}
        <img
          class="border-default h-8 w-8 shrink-0 rounded-md border object-contain"
          src={theme.logo_url}
          alt={m.widget_admin_logo_preview_alt()}
          width="32"
          height="32"
        />
      {/if}
    </div>
    <Field.Description id={id("logo-url-help")}
      >{m.widget_admin_logo_url_description()}</Field.Description
    >
  </Field.Field>

  <Field.Separator />

  <Field.Group class="grid gap-6 sm:grid-cols-2">
    <Field.Field>
      <Field.Label for={id("scheme")}>{m.widget_admin_color_scheme()}</Field.Label>
      <Select.Root
        type="single"
        value={theme.color_scheme ?? "auto"}
        onValueChange={(value) =>
          onChange({ color_scheme: value as NonNullable<WidgetTheme["color_scheme"]> })}
      >
        <Select.Trigger id={id("scheme")} class="w-full" aria-describedby={id("scheme-help")}>
          <span data-slot="select-value">{schemeLabels[theme.color_scheme ?? "auto"]}</span>
        </Select.Trigger>
        <Select.Content>
          {#each Object.entries(schemeLabels) as [value, label] (value)}
            <Select.Item {value} {label}>{label}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
      <Field.Description id={id("scheme-help")}
        >{m.widget_admin_color_scheme_description()}</Field.Description
      >
    </Field.Field>

    <Field.Field>
      <Field.Label for={id("position")}>{m.widget_admin_position()}</Field.Label>
      <Select.Root
        type="single"
        value={theme.position ?? "bottom-right"}
        onValueChange={(value) =>
          onChange({ position: value as NonNullable<WidgetTheme["position"]> })}
      >
        <Select.Trigger id={id("position")} class="w-full" aria-describedby={id("position-help")}>
          <span data-slot="select-value">{positionLabels[theme.position ?? "bottom-right"]}</span>
        </Select.Trigger>
        <Select.Content>
          {#each Object.entries(positionLabels) as [value, label] (value)}
            <Select.Item {value} {label}>{label}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
      <Field.Description id={id("position-help")}
        >{m.widget_admin_position_description()}</Field.Description
      >
    </Field.Field>

    <Field.Field>
      <Field.Label for={id("radius")}>{m.widget_admin_radius()}</Field.Label>
      <Input
        id={id("radius")}
        type="number"
        min={0}
        max={24}
        step={1}
        class="max-w-32"
        value={theme.radius ?? 12}
        aria-describedby={id("radius-help")}
        oninput={(event) =>
          number(event, (value) => onChange({ radius: Math.min(24, Math.max(0, value)) }))}
      />
      <Field.Description id={id("radius-help")}
        >{m.widget_admin_radius_description()}</Field.Description
      >
    </Field.Field>
  </Field.Group>
</Field.Group>
