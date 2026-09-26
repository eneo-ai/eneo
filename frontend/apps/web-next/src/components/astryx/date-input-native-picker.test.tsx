// @vitest-environment jsdom
import { DateInput } from "@astryxdesign/core/DateInput";
import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

afterEach(() => vi.restoreAllMocks());

// Guards frontend/patches/@astryxdesign%2Fcore@0.6.3.patch. Unpatched, Astryx
// passes `nativePicker` (which we set to keep its CSP-blocked engine probe
// away) on to the field's <div>, and React warns about an unknown DOM prop.
// After an Astryx upgrade bun silently skips a stale patch; this test then
// fails: recreate the patch with `bun patch @astryxdesign/core` (or drop it
// if Astryx fixed DateInput).
it("keeps nativePicker off the DOM", () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  renderInApp(
    <DateInput
      label="Från"
      value={undefined}
      onChange={() => {}}
      nativePicker="never"
      format="date"
    />
  );

  expect(screen.getAllByText("Från").length).toBeGreaterThan(0);
  expect(document.querySelector("[nativepicker], [nativePicker]")).toBeNull();
  const warnings = error.mock.calls.map((call) => call.map(String).join(" "));
  expect(warnings.filter((warning) => /nativePicker/i.test(warning))).toEqual([]);
});
