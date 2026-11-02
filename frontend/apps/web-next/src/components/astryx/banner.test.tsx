// @vitest-environment jsdom
import { Banner } from "@astryxdesign/core/Banner";
import { screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { AnnouncedBanner, QuietBanner } from "./banner";

it("is Astryx's error banner, which is not a live region", () => {
  renderInApp(<Banner status="error" title="Astryx" collapsible={false} />);

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

  expect(screen.queryAllByRole("alert")).toHaveLength(0);
  expect(ref.current?.hasAttribute("role")).toBe(false);
  expect(ref.current?.getAttribute("tabindex")).toBe("-1");
  expect(ref.current?.textContent).toContain("Synken misslyckades");
  expect(ref.current?.textContent).toContain("Se vad som hände under Problem.");
  expect(screen.getByRole("button", { name: "Visa problem" })).toBeTruthy();
});

it("makes an outcome banner an alert, as Astryx 0.6 did for errors and warnings", () => {
  renderInApp(<AnnouncedBanner status="error" title="Det gick inte att spara" />);
  renderInApp(<AnnouncedBanner status="info" title="Sparat" />);

  expect(screen.getByText("Det gick inte att spara").closest('[role="alert"]')).not.toBeNull();
  expect(screen.getByText("Sparat").closest('[role="status"]')).not.toBeNull();
});
