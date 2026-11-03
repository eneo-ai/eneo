// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { texts } from "./fixtures";
import { WidgetMockPreview } from "./widget-mock-preview";

describe("WidgetMockPreview", () => {
  it("renders the template's texts and persona as one described image", async () => {
    const { container } = renderInApp(
      <WidgetMockPreview
        name="Kommunmallen"
        texts={{
          ...texts,
          footer_text: "Läs mer",
          footer_link_url: "https://www.kommun.se/policy"
        }}
        theme={{ primary_color: "#1F4E79", radius: 8, position: "bottom-left" }}
        persona={{ name: "Sigge", avatar_icon_id: null, avatar_in_launcher: false }}
      />
    );
    const image = screen.getByRole("img", {
      name: /Statisk förhandsgranskning av mallen Kommunmallen/
    });
    expect(image.textContent).toContain("Fråga oss");
    expect(image.textContent).toContain("Hej!");
    expect(image.textContent).toContain("Sigge");
    expect(image.textContent).toContain("www.kommun.se");
    expect(screen.getByRole("heading", { level: 2, name: "Förhandsgranskning" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "Fråga oss" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("pins the scheme toggle when the template pins a scheme", () => {
    renderInApp(
      <WidgetMockPreview
        name="Mörk"
        texts={texts}
        theme={{ primary_color: "#1F4E79", color_scheme: "dark" }}
      />
    );
    const dark = screen.getByRole("button", { name: "Mörkt", pressed: true });
    expect(dark.hasAttribute("disabled") || dark.getAttribute("aria-disabled") === "true").toBe(
      true
    );
  });

  it("marks the chosen scheme with a check and moves it when the preview changes", () => {
    renderInApp(<WidgetMockPreview name="Kommunmallen" texts={texts} theme={{}} />);
    const schemes = within(
      screen.getByRole("group", { name: "Färgschema i förhandsgranskningen" })
    );
    const selected = schemes.getByRole("button", { pressed: true });
    const other = schemes.getByRole("button", { pressed: false });
    const nextScheme = other === schemes.getByRole("button", { name: "Mörkt" }) ? "dark" : "light";
    expect(selected.querySelector("svg.lucide-check")).toBeTruthy();
    expect(other.querySelector("svg.lucide-check")).toBeNull();
    fireEvent.click(other);
    expect(other.getAttribute("aria-pressed")).toBe("true");
    expect(other.querySelector("svg.lucide-check")).toBeTruthy();
    expect(selected.querySelector("svg.lucide-check")).toBeNull();
    expect(
      screen
        .getByRole("img", { name: /Statisk förhandsgranskning av mallen Kommunmallen/ })
        .getAttribute("data-theme")
    ).toBe(nextScheme);
  });
});
