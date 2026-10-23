import { afterEach, describe, expect, it } from "vitest";
import { focusAfterRemoval } from "./focusAfterRemoval";

function table(rows: string[]) {
  const region = document.createElement("section");
  region.dataset.focusRegion = "";
  region.innerHTML = `<h2 tabindex="-1" data-content-heading>Folders</h2>
    <table><tbody>${rows
      .map(
        (name) =>
          `<tr><td><a href="#${name}">${name}</a></td><td><button>${name} menu</button></td></tr>`
      )
      .join("")}</tbody></table>`;
  document.body.append(region);
  return region;
}

const menu = (region: HTMLElement, name: string) =>
  [...region.querySelectorAll("button")].find((button) => button.textContent === `${name} menu`)!;

describe("focusAfterRemoval", () => {
  afterEach(() => document.body.replaceChildren());

  it("moves focus to the row that took the removed row's place", () => {
    const region = table(["a", "b", "c"]);
    const removal = focusAfterRemoval(menu(region, "b"));
    menu(region, "b").closest("tr")!.remove();

    expect(removal.settle()).toBe(true);
    expect(document.activeElement?.textContent).toBe("c");
  });

  it("falls back to the row before the last one, then to the region's heading", () => {
    const region = table(["a", "b"]);
    const last = focusAfterRemoval(menu(region, "b"));
    menu(region, "b").closest("tr")!.remove();
    expect(last.settle()).toBe(true);
    expect(document.activeElement?.textContent).toBe("a");

    const only = focusAfterRemoval(menu(region, "a"));
    menu(region, "a").closest("tr")!.remove();
    expect(only.settle()).toBe(true);
    expect(document.activeElement?.textContent).toBe("Folders");
  });

  it("leaves focus alone while the control is still there", () => {
    const region = table(["a"]);
    expect(focusAfterRemoval(menu(region, "a")).settle()).toBe(false);
    expect(focusAfterRemoval(null).settle()).toBe(false);
  });
});
