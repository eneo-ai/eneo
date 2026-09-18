<!-- Appearance: colours, logo, shape and placement of the launcher. -->
<script lang="ts">
  import type { WidgetTheme } from "@eneo/eneo-js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { IconEneo } from "@eneo/icons/eneo";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { isHttpUrl } from "../urls";
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

  // The logo address is committed when the field is left, never per keystroke.
  let logoDraft = $state(untrack(() => theme.logo_url ?? ""));
  let logoInvalid = $state(false);
  let logoBroken = $state(false);
  let lastSavedLogo = untrack(() => theme.logo_url ?? "");
  $effect(() => {
    // Follow a new saved value (template applied, other tab) without ever
    // touching what is being typed.
    const saved = theme.logo_url ?? "";
    if (saved !== lastSavedLogo) {
      lastSavedLogo = saved;
      logoDraft = saved;
      logoInvalid = false;
    }
  });

  function commitLogo() {
    const trimmed = logoDraft.trim();
    if (trimmed === "") {
      logoInvalid = false;
      if (theme.logo_url) onChange({ logo_url: null });
      return;
    }
    logoInvalid = !isHttpUrl(trimmed);
    if (!logoInvalid && trimmed !== theme.logo_url) {
      logoBroken = false;
      onChange({ logo_url: trimmed });
    }
  }

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

  <Field.Set class="border-default rounded-lg border p-4">
    <div class="flex items-start justify-between gap-4">
      <div class="flex flex-col gap-1">
        <Field.Legend>{m.widget_admin_dark_mode()}</Field.Legend>
        <Field.Description id={id("dark-mode-help")}
          >{m.widget_admin_dark_mode_description()}</Field.Description
        >
      </div>
      <Field.Field orientation="horizontal" class="w-auto shrink-0">
        <Field.Label for={id("dark-mode-custom")}>{m.widget_admin_dark_mode_custom()}</Field.Label>
        <Switch
          id={id("dark-mode-custom")}
          checked={customDark}
          aria-describedby={id("dark-mode-help")}
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
          onChange={(value) => onChange({ primary_color_dark: value })}
        />
        <ColorField
          id={id("header-color-dark")}
          label={m.widget_admin_header_color_dark()}
          description={m.widget_admin_header_color_dark_description()}
          value={theme.header_color_dark ?? null}
          clearable
          onChange={(value) => onChange({ header_color_dark: value })}
        />
      </Field.Group>
    {/if}
  </Field.Set>

  <Field.Field data-invalid={logoInvalid || undefined}>
    <Field.Label for={id("logo-url")}>{m.widget_admin_logo_url()}</Field.Label>
    <div class="flex items-center gap-3">
      <span
        class="border-default bg-primary flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-md border"
        aria-hidden="true"
      >
        {#if theme.logo_url && !logoBroken}
          <img
            class="h-8 w-8 object-contain"
            src={theme.logo_url}
            alt=""
            width="32"
            height="32"
            onerror={() => (logoBroken = true)}
            onload={() => (logoBroken = false)}
          />
        {:else}
          <IconEneo size="md" class="text-brand-eneo" viewBox="0 -21 214 214" />
        {/if}
      </span>
      <Input
        id={id("logo-url")}
        type="url"
        maxlength={500}
        aria-invalid={logoInvalid}
        aria-describedby={id("logo-url-help")}
        bind:value={logoDraft}
        onchange={commitLogo}
        onkeydown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commitLogo();
          }
        }}
      />
    </div>
    <Field.Description id={id("logo-url-help")}>
      {theme.logo_url ? m.widget_admin_logo_url_description() : m.widget_admin_logo_url_default()}
    </Field.Description>
    {#if logoInvalid}
      <Field.Error>{m.widget_admin_url_invalid()}</Field.Error>
    {:else if logoBroken}
      <Field.Error>{m.widget_admin_logo_broken()}</Field.Error>
    {/if}
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
