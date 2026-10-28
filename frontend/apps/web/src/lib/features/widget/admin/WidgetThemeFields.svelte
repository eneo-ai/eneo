<!-- Appearance: colours, shape and placement of the launcher. -->
<script lang="ts">
  import type { WidgetTheme } from "@eneo/eneo-js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import ColorField from "./ColorField.svelte";

  type Props = {
    theme: WidgetTheme;
    onChange: (change: Partial<WidgetTheme>) => void;
    idPrefix?: string;
    /** The whole appearance is governed by a template; `lockHint` says so. */
    locked?: boolean;
    lockHint?: string;
    /** Id of an error about the whole appearance, which every control points to. */
    errorId?: string;
  };

  let {
    theme,
    onChange,
    idPrefix = "widget",
    locked = false,
    lockHint = "",
    errorId
  }: Props = $props();

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

  // Dark mode shows its own colour fields once switched on; switching off
  // clears them so dark mode falls back to the light-mode colours.
  const hasDarkColors = $derived(!!(theme.primary_color_dark || theme.header_color_dark));
  let customDark = $state(untrack(() => hasDarkColors));
  $effect(() => {
    if (hasDarkColors) customDark = true;
  });
  function toggleDark(checked: boolean) {
    customDark = checked;
    if (!checked && hasDarkColors) onChange({ primary_color_dark: null, header_color_dark: null });
  }

  // The API stores the radius as a whole number of pixels; a fraction stays
  // in the field with an error instead of failing the save.
  let radiusInvalid = $state(false);
  function radius(event: Event) {
    const raw = (event.currentTarget as HTMLInputElement).value;
    const value = Number(raw);
    radiusInvalid = raw !== "" && !Number.isInteger(value);
    if (raw !== "" && Number.isInteger(value))
      onChange({ radius: Math.min(24, Math.max(0, value)) });
  }

  // The lock hint and an appearance-wide error must reach every control; a
  // describedby on the group's div is not exposed to assistive technology.
  const lockRef = $derived([locked && id("lock-hint"), errorId].filter(Boolean).join(" "));
  const describedBy = (help: string) => (lockRef ? `${id(help)} ${lockRef}` : id(help));
</script>

<!-- One native fieldset: disabling it freezes every control below at once. -->
<fieldset class="m-0 min-w-0 border-0 p-0" disabled={locked || undefined}>
  {#if locked}
    <p id={id("lock-hint")} class="text-secondary mb-4 text-sm">{lockHint}</p>
  {/if}
  <Field.Group class="grid gap-6">
    <ColorField
      id={id("primary-color")}
      label={m.widget_admin_primary_color()}
      description={m.widget_admin_primary_color_description()}
      value={theme.primary_color ?? null}
      checkContrast
      disabled={locked}
      describedBy={lockRef}
      onChange={(value) => onChange({ primary_color: value ?? "" })}
    />

    <ColorField
      id={id("header-color")}
      label={m.widget_admin_header_color()}
      description={m.widget_admin_header_color_description()}
      value={theme.header_color ?? null}
      clearable
      checkTextOn
      disabled={locked}
      describedBy={lockRef}
      onChange={(value) => onChange({ header_color: value })}
    />

    <Field.Set class="border-default rounded-lg border p-4">
      <div class="flex items-start justify-between gap-4">
        <div class="flex flex-col gap-1">
          <Field.Legend>{m.widget_admin_dark_mode()}</Field.Legend>
          <Field.Description id={id("dark-mode-help")}
            >{m.widget_admin_dark_mode_description()}</Field.Description
          >
        </div>
        <Field.Field orientation="horizontal" class="w-auto shrink-0">
          <Field.Label for={id("dark-mode-custom")}>{m.widget_admin_dark_mode_custom()}</Field.Label
          >
          <Switch
            id={id("dark-mode-custom")}
            checked={customDark}
            aria-describedby={[id("dark-mode-help"), errorId].filter(Boolean).join(" ")}
            onCheckedChange={toggleDark}
          />
        </Field.Field>
      </div>
      {#if customDark}
        <Field.Group class="grid gap-6 pt-2">
          <ColorField
            id={id("primary-color-dark")}
            label={m.widget_admin_primary_color_dark()}
            description={m.widget_admin_primary_color_dark_description()}
            value={theme.primary_color_dark ?? null}
            clearable
            checkContrast
            surface="dark"
            disabled={locked}
            describedBy={lockRef}
            onChange={(value) => onChange({ primary_color_dark: value })}
          />
          <ColorField
            id={id("header-color-dark")}
            label={m.widget_admin_header_color_dark()}
            description={m.widget_admin_header_color_dark_description()}
            value={theme.header_color_dark ?? null}
            clearable
            checkTextOn
            disabled={locked}
            describedBy={lockRef}
            onChange={(value) => onChange({ header_color_dark: value })}
          />
        </Field.Group>
      {/if}
    </Field.Set>

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
          <Select.Trigger
            id={id("scheme")}
            class="w-full"
            aria-describedby={describedBy("scheme-help")}
          >
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
          <Select.Trigger
            id={id("position")}
            class="w-full"
            aria-describedby={describedBy("position-help")}
          >
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

      <Field.Field data-invalid={radiusInvalid || undefined}>
        <Field.Label for={id("radius")}>{m.widget_admin_radius()}</Field.Label>
        <Input
          id={id("radius")}
          type="number"
          min={0}
          max={24}
          step={1}
          class="max-w-32"
          value={theme.radius ?? 12}
          aria-invalid={radiusInvalid}
          aria-describedby={radiusInvalid
            ? `${describedBy("radius-help")} ${id("radius-error")}`
            : describedBy("radius-help")}
          oninput={radius}
        />
        <Field.Description id={id("radius-help")}
          >{m.widget_admin_radius_description()}</Field.Description
        >
        {#if radiusInvalid}
          <Field.Error id={id("radius-error")}
            >{m.widget_admin_value_out_of_range({ min: "0", max: "24" })}</Field.Error
          >
        {/if}
      </Field.Field>
    </Field.Group>
  </Field.Group>
</fieldset>
