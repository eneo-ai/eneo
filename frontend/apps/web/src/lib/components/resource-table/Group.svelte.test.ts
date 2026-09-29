import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it } from "vitest";
import "../../../app.css";
import GroupTestHost from "./GroupTestHost.svelte";

describe("resource table group", () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = "light";
  });

  it("keeps an open titled group's toggle unfilled", async () => {
    render(GroupTestHost, { title: "Published" });

    const toggle = page.getByRole("button", { name: "Published" });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "true");
    const unfilled = getComputedStyle(document.body.appendChild(document.createElement("span")));
    expect(getComputedStyle(toggle.element()).backgroundColor).toBe(unfilled.backgroundColor);
  });

  it("makes the chevron the toggle when the title is blank", async () => {
    render(GroupTestHost, { title: " ", toggleLabel: "Anthropic" });

    const toggle = page.getByRole("button", { name: "Anthropic" });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "true");
    await toggle.click();
    await expect.element(toggle).toHaveAttribute("aria-expanded", "false");
    const header = document.querySelector("tbody tr")!;
    expect(header.querySelectorAll("button")).toHaveLength(1);
  });
});
