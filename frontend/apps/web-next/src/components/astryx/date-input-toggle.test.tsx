// @vitest-environment jsdom
import { DateInput } from "@astryxdesign/core/DateInput";
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";

// globals.css (section 11) makes Astryx DateInput's calendar toggle a 24 px
// target, 44 px on touch. The button has no class of its own, so the rule
// finds it by the markup around it. After an Astryx upgrade that moved it,
// this fails: update the selector there, or drop the rule if Astryx sizes the
// toggle itself.
it("keeps the calendar toggle where globals.css finds it", () => {
  renderInApp(
    <DateInput
      label="Från"
      value={undefined}
      onChange={() => {}}
      nativePicker="never"
      format="date"
    />
  );

  const toggle = screen.getByRole("button", { name: "Öppna kalender" });
  expect(toggle.matches(".astryx-date-input > button:has(> .astryx-date-input-toggle-icon)")).toBe(
    true
  );
});
