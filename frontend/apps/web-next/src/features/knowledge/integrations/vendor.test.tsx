// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { VendorIcon } from "./vendor";

afterEach(cleanup);

describe("VendorIcon", () => {
  it("shows the vendor's public logo as a decorative image of the given size", async () => {
    const { container } = render(<VendorIcon type="sharepoint" size={32} />);
    const logo = container.querySelector("img");
    expect(logo?.getAttribute("src")).toBe("/integration-logos/sharepoint.png");
    expect(logo?.getAttribute("alt")).toBe("");
    expect(logo?.getAttribute("width")).toBe("32");
    expect(logo?.getAttribute("height")).toBe("32");
    await expectNoAxeViolations(container);
  });
});
