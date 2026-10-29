// @vitest-environment jsdom
import { screen } from "@testing-library/react";
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
});
