import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it } from "vitest";
import "../../app.css";
import IconSizingTestHost from "./IconSizingTestHost.svelte";

const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
const width = (element: Element) => parseFloat(getComputedStyle(element).width);

describe("@eneo/icons sizing", () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = "light";
    render(IconSizingTestHost);
  });

  it("uses the icon's default size, also inside shadcn buttons", async () => {
    const plain = page.getByTestId("plain").element().querySelector("svg")!;
    const inIconButton = page.getByTestId("icon-button").element().querySelector("svg")!;
    const inSmallButton = page.getByTestId("small-button").element().querySelector("svg")!;
    expect(width(plain)).toBe(1.5 * rem);
    expect(width(inIconButton)).toBe(1.5 * rem);
    expect(width(inSmallButton)).toBe(1.5 * rem);
  });

  it("lets a size class on the icon win", async () => {
    const sized = page.getByTestId("sized").element().querySelector("svg")!;
    expect(width(sized)).toBe(rem);
  });
});
