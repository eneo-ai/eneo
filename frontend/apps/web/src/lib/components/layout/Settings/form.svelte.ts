import { m } from "$lib/paraglide/messages";

/**
 * Reactive field primitives for admin settings forms.
 *
 * Every field tracks a canonical value (what the API stores) separately from
 * the raw display string, so inputs can be denominated in friendlier units
 * (MB, KB) while the API keeps bytes. Validation happens on every keystroke;
 * `error` is a localized message and `value` is `undefined` while invalid.
 */

export type NumberFieldConfig = {
  /** Canonical initial value, `null` when unset. */
  initial: number | null;
  /** Canonical units per display unit (e.g. 1048576 for MB inputs). */
  scale?: number;
  /** Inclusive canonical bounds. */
  min?: number;
  max?: number | null;
  /** Empty input is invalid instead of meaning "unset". */
  required?: boolean;
};

type ParseResult = { value: number | null | undefined; error: string | null };

function formatDisplay(canonical: number | null, scale: number): string {
  if (canonical == null) return "";
  const display = canonical / scale;
  if (Number.isInteger(display)) return String(display);
  return String(Math.round(display * 100) / 100);
}

function parseRaw(
  raw: string,
  { scale, min, max, required }: Required<Omit<NumberFieldConfig, "initial">>
): ParseResult {
  const normalized = raw.trim().replace(",", ".");
  if (normalized === "") {
    if (required) return { value: undefined, error: m.flow_settings_error_required() };
    return { value: null, error: null };
  }
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || (scale === 1 && !Number.isInteger(parsed))) {
    return { value: undefined, error: m.flow_settings_error_integer() };
  }
  const canonical = Math.round(parsed * scale);
  if (max != null && (canonical < min || canonical > max)) {
    return {
      value: undefined,
      error: m.flow_settings_error_range({
        min: formatDisplay(min, scale),
        max: formatDisplay(max, scale)
      })
    };
  }
  if (canonical < min) {
    return {
      value: undefined,
      error: m.flow_settings_error_min({ min: formatDisplay(min, scale) })
    };
  }
  return { value: canonical, error: null };
}

export class NumberField {
  raw = $state("");
  #initial = $state<number | null>(null);
  readonly scale: number;
  readonly #rules: Required<Omit<NumberFieldConfig, "initial">>;

  constructor(config: NumberFieldConfig) {
    this.scale = config.scale ?? 1;
    this.#rules = {
      scale: this.scale,
      min: config.min ?? 1,
      max: config.max ?? null,
      required: config.required ?? false
    };
    this.#initial = config.initial;
    this.raw = formatDisplay(config.initial, this.scale);
  }

  #parsed = $derived.by<ParseResult>(() => {
    // Display rounding (e.g. 25 000 000 B → "23.84" MB) must never make an
    // untouched field dirty or rewrite its stored value: while the raw text
    // still round-trips the baseline display, the exact canonical baseline is
    // the value.
    if (this.#initial != null && this.raw.trim() === formatDisplay(this.#initial, this.scale)) {
      return { value: this.#initial, error: null };
    }
    return parseRaw(this.raw, this.#rules);
  });

  /** Canonical value; `null` = unset, `undefined` = currently invalid. */
  get value(): number | null | undefined {
    return this.#parsed.value;
  }

  get error(): string | null {
    return this.#parsed.error;
  }

  get dirty(): boolean {
    if (this.#parsed.value === undefined) {
      return this.raw.trim() !== formatDisplay(this.#initial, this.scale);
    }
    return this.#parsed.value !== this.#initial;
  }

  reset(): void {
    this.raw = formatDisplay(this.#initial, this.scale);
  }

  /** Adopt the server-confirmed value as the new baseline. */
  commit(next: number | null): void {
    this.#initial = next;
    this.raw = formatDisplay(next, this.scale);
  }
}

export class ToggleField {
  value = $state(false);
  #initial = $state(false);

  constructor(initial: boolean) {
    this.#initial = initial;
    this.value = initial;
  }

  get error(): null {
    return null;
  }

  get dirty(): boolean {
    return this.value !== this.#initial;
  }

  reset(): void {
    this.value = this.#initial;
  }

  commit(next: boolean): void {
    this.#initial = next;
    this.value = next;
  }
}

/**
 * A switch plus a number that is only meaningful while the switch is on.
 * Canonical value is `null` when off, a required number when on.
 */
export class ToggleNumberField {
  enabled = $state(false);
  raw = $state("");
  #initial = $state<number | null>(null);
  readonly scale: number;
  readonly #rules: Required<Omit<NumberFieldConfig, "initial">>;
  readonly #suggestion: number | null;

  constructor(config: NumberFieldConfig & { suggestion?: number }) {
    this.scale = config.scale ?? 1;
    this.#rules = {
      scale: this.scale,
      min: config.min ?? 1,
      max: config.max ?? null,
      required: true
    };
    this.#suggestion = config.suggestion ?? null;
    this.#initial = config.initial;
    this.enabled = config.initial != null;
    this.raw = formatDisplay(config.initial, this.scale);
  }

  /** Prefill the editable suggestion when the switch turns on with no value. */
  applySuggestion(): void {
    if (this.enabled && this.raw.trim() === "" && this.#suggestion != null) {
      this.raw = formatDisplay(this.#suggestion, this.scale);
    }
  }

  #parsed = $derived.by<ParseResult>(() => {
    if (!this.enabled) return { value: null, error: null };
    // Same lossless round-trip rule as NumberField: an untouched display
    // string keeps the exact canonical baseline.
    if (this.#initial != null && this.raw.trim() === formatDisplay(this.#initial, this.scale)) {
      return { value: this.#initial, error: null };
    }
    return parseRaw(this.raw, this.#rules);
  });

  get value(): number | null | undefined {
    return this.#parsed.value;
  }

  get error(): string | null {
    return this.#parsed.error;
  }

  get dirty(): boolean {
    if (this.#parsed.value === undefined) return true;
    return this.#parsed.value !== this.#initial;
  }

  reset(): void {
    this.enabled = this.#initial != null;
    this.raw = formatDisplay(this.#initial, this.scale);
  }

  commit(next: number | null): void {
    this.#initial = next;
    this.enabled = next != null;
    this.raw = formatDisplay(next, this.scale);
  }
}

export type SettingsField = NumberField | ToggleField | ToggleNumberField;

export class SettingsForm {
  readonly #fields: SettingsField[];

  constructor(fields: SettingsField[]) {
    this.#fields = fields;
  }

  get dirtyCount(): number {
    return this.#fields.filter((field) => field.dirty).length;
  }

  get invalid(): boolean {
    return this.#fields.some((field) => field.error !== null);
  }

  resetAll(): void {
    for (const field of this.#fields) field.reset();
  }
}
