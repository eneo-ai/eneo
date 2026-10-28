// @vitest-environment jsdom
import { Banner } from "@astryxdesign/core/Banner";
import { screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { QuietBanner } from "./banner";

// Astryx 0.6.4 makes an error banner an assertive alert. When it stops doing
// so, QuietBanner and this test can go.
it("is Astryx's error banner without the alert role that reads it out on every mount", () => {
  renderInApp(<Banner status="error" title="Astryx" collapsible={false} />);
  expect(screen.getByRole("alert").textContent).toContain("Astryx");

  const ref = createRef<HTMLDivElement>();
  renderInApp(
    <QuietBanner
      ref={ref}
      tabIndex={-1}
      status="error"
      title="Synken misslyckades"
      description="Se vad som hände under Problem."
      collapsible={false}
      endContent={<button type="button">Visa problem</button>}
    />
  );

  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(ref.current?.hasAttribute("role")).toBe(false);
  expect(ref.current?.getAttribute("tabindex")).toBe("-1");
  expect(ref.current?.textContent).toContain("Synken misslyckades");
  expect(ref.current?.textContent).toContain("Se vad som hände under Problem.");
  expect(screen.getByRole("button", { name: "Visa problem" })).toBeTruthy();
});
