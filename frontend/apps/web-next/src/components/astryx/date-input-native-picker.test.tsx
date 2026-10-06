// @vitest-environment jsdom
import { DateInput } from "@astryxdesign/core/DateInput";
import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

afterEach(() => vi.restoreAllMocks());

// Astryx 0.6.3 passed `nativePicker` on to the field's <div> (React warned
// about an unknown DOM prop); we patched it. 0.6.4 deprecates `nativePicker`
// for `presentation` and strips both before the DOM. This keeps guarding that
// neither prop leaks on an upgrade (`presentation="adaptive-bottom-sheet"` is
// what keeps the CSP-blocked browser-picker probe away).
it("keeps presentation and nativePicker off the DOM", () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  renderInApp(
    <DateInput
      label="Från"
      value={undefined}
      onChange={() => {}}
      presentation="adaptive-bottom-sheet"
      format="date"
    />
  );

  expect(screen.getAllByText("Från").length).toBeGreaterThan(0);
  expect(document.querySelector("[presentation], [nativepicker], [nativePicker]")).toBeNull();
  const warnings = error.mock.calls.map((call) => call.map(String).join(" "));
  expect(warnings.filter((warning) => /nativePicker|presentation/i.test(warning))).toEqual([]);
});
