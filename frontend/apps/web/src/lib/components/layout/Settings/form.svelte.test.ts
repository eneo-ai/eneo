import { describe, expect, it } from "vitest";

import { NumberField, SettingsForm, ToggleField, ToggleNumberField } from "./form.svelte";

const MB = 1024 * 1024;

describe("NumberField", () => {
  it("keeps a byte value that does not divide evenly by the display unit lossless", () => {
    // 25 000 000 B displays as "23.84" MB; reparsing that rounded display must
    // not mark the field dirty or change the value that would be saved.
    const field = new NumberField({ initial: 25_000_000, scale: MB, min: 1 });

    expect(field.raw).toBe("23.84");
    expect(field.dirty).toBe(false);
    expect(field.error).toBeNull();
    expect(field.value).toBe(25_000_000);
  });

  it("converts edited display units back to canonical units", () => {
    const field = new NumberField({ initial: 10 * MB, scale: MB, min: 1 });

    field.raw = "200";

    expect(field.dirty).toBe(true);
    expect(field.value).toBe(200 * MB);
  });

  it("accepts Swedish decimal commas on scaled fields", () => {
    const field = new NumberField({ initial: null, scale: MB, min: 1 });

    field.raw = "0,5";

    expect(field.value).toBe(Math.round(0.5 * MB));
    expect(field.error).toBeNull();
  });

  it("enforces the 2 GiB upload ceiling in display units", () => {
    const GIB2 = 2 * 1024 * MB;
    const field = new NumberField({ initial: 10 * MB, scale: MB, min: 1, max: GIB2 });

    field.raw = "2049";
    expect(field.error).not.toBeNull();
    expect(field.value).toBeUndefined();

    field.raw = "2048";
    expect(field.error).toBeNull();
    expect(field.value).toBe(GIB2);
  });

  it("rejects fractions on unscaled fields and bounds on scaled ones", () => {
    const count = new NumberField({ initial: 10, min: 1, max: 1000 });
    count.raw = "1.5";
    expect(count.error).not.toBeNull();
    expect(count.value).toBeUndefined();

    count.raw = "2000";
    expect(count.error).not.toBeNull();

    const empty = new NumberField({ initial: 5, min: 1, required: true });
    empty.raw = "";
    expect(empty.error).not.toBeNull();
  });

  it("treats empty optional input as unset and resets to the baseline", () => {
    const field = new NumberField({ initial: 7, min: 1 });

    field.raw = "";
    expect(field.value).toBeNull();
    expect(field.dirty).toBe(true);

    field.reset();
    expect(field.raw).toBe("7");
    expect(field.dirty).toBe(false);
  });

  it("adopts committed server values as the new lossless baseline", () => {
    const field = new NumberField({ initial: 10 * MB, scale: MB, min: 1 });

    field.raw = "25";
    field.commit(25 * MB);

    expect(field.dirty).toBe(false);
    expect(field.value).toBe(25 * MB);
  });
});

describe("ToggleNumberField", () => {
  it("is null while disabled and requires a value while enabled", () => {
    const field = new ToggleNumberField({ initial: null, min: 1 });

    expect(field.value).toBeNull();
    expect(field.dirty).toBe(false);

    field.enabled = true;
    expect(field.error).not.toBeNull();
    expect(field.dirty).toBe(true);
  });

  it("prefills the editable suggestion only when empty", () => {
    const field = new ToggleNumberField({ initial: null, min: 1, suggestion: 100 });

    field.enabled = true;
    field.applySuggestion();
    expect(field.raw).toBe("100");
    expect(field.value).toBe(100);

    field.raw = "40";
    field.applySuggestion();
    expect(field.raw).toBe("40");
  });

  it("round-trips its baseline losslessly like NumberField", () => {
    const field = new ToggleNumberField({ initial: 25_000_000, scale: MB, min: 1 });

    expect(field.enabled).toBe(true);
    expect(field.dirty).toBe(false);
    expect(field.value).toBe(25_000_000);

    field.enabled = false;
    expect(field.value).toBeNull();
    field.reset();
    expect(field.enabled).toBe(true);
    expect(field.dirty).toBe(false);
  });
});

describe("SettingsForm", () => {
  it("counts dirty fields and flags invalid state across field kinds", () => {
    const days = new NumberField({ initial: 30, min: 1, max: 2555 });
    const toggle = new ToggleField(false);
    const form = new SettingsForm([days, toggle]);

    expect(form.dirtyCount).toBe(0);
    expect(form.invalid).toBe(false);

    toggle.value = true;
    days.raw = "abc";
    expect(form.dirtyCount).toBe(2);
    expect(form.invalid).toBe(true);

    form.resetAll();
    expect(form.dirtyCount).toBe(0);
    expect(form.invalid).toBe(false);
  });
});
